using System.Diagnostics;
using Microsoft.AspNetCore.Http.HttpResults;
using Microsoft.AspNetCore.Mvc;
using MovieSearch.Api.Contracts;
using MovieSearch.Api.Security;
using MovieSearch.Application.Auth;
using MovieSearch.Application.Movies;
using MovieSearch.Domain.Entities;
using MovieSearch.Domain.Exceptions;
using MovieSearch.Domain.ValueObjects;

namespace MovieSearch.Api.Endpoints;

/// <summary>The movie endpoints under <c>/api/v1</c>.</summary>
internal static class MovieEndpoints
{
    /// <summary>Map every movie endpoint.</summary>
    /// <param name="app">Route builder.</param>
    /// <returns>The same route builder.</returns>
    public static IEndpointRouteBuilder MapMovieEndpoints(this IEndpointRouteBuilder app)
    {
        // Every route in the group needs a token and is rate limited. Applying
        // both to the group rather than to each route means a new endpoint
        // cannot be added without them by forgetting a line.
        var movies = app.MapGroup("/api/v1/movies")
            .RequireAuthorization(AuthorizationPolicies.Reader)
            .RequireRateLimiting(RateLimitPolicies.PerClient)
            .WithTags("Movies");

        movies.MapGet("/search", SearchAsync)
            .WithName("SearchMovies")
            .WithSummary("Search movies with a natural language description.")
            .WithDescription(
                "Runs a semantic vector search over the catalogue and narrows it with the " +
                "metadata filters supplied. The description is matched by meaning; every " +
                "filter is an exact match. Results are ordered by similarity, best first.")
            .Produces<SearchResponse>(StatusCodes.Status200OK)
            .ProducesProblem(StatusCodes.Status400BadRequest)
            .ProducesProblem(StatusCodes.Status401Unauthorized)
            .ProducesProblem(StatusCodes.Status429TooManyRequests)
            .ProducesProblem(StatusCodes.Status502BadGateway);

        // The literal route is declared before the parameter route so that the
        // intent is obvious to a reader, even though routing would prefer the
        // literal in either order.
        movies.MapGet("/genres", GetGenresAsync)
            .WithName("ListGenres")
            .WithSummary("List every genre in the catalogue.")
            .WithDescription("The values returned here are the accepted values of the `genre` filter.")
            .Produces<GenresResponse>(StatusCodes.Status200OK)
            .ProducesProblem(StatusCodes.Status401Unauthorized)
            .ProducesProblem(StatusCodes.Status502BadGateway);

        movies.MapGet("/{id:guid}", GetByIdAsync)
            .WithName("GetMovieById")
            .WithSummary("Fetch one movie by its identifier.")
            .Produces<MovieResponse>(StatusCodes.Status200OK)
            .ProducesProblem(StatusCodes.Status404NotFound)
            .ProducesProblem(StatusCodes.Status401Unauthorized)
            .ProducesProblem(StatusCodes.Status502BadGateway);

        movies.MapGet("/{id:guid}/similar", GetSimilarAsync)
            .WithName("GetSimilarMovies")
            .WithSummary("Fetch the movies closest in meaning to one movie.")
            .WithDescription(
                "Compares the stored vector of the given movie against every other vector. " +
                "The movie itself is never in the result.")
            .Produces<SimilarMoviesResponse>(StatusCodes.Status200OK)
            .ProducesProblem(StatusCodes.Status400BadRequest)
            .ProducesProblem(StatusCodes.Status404NotFound)
            .ProducesProblem(StatusCodes.Status401Unauthorized)
            .ProducesProblem(StatusCodes.Status502BadGateway);

        // Statistics describe the whole corpus, so they sit behind the admin
        // role while search stays open to a reader.
        app.MapGet("/api/v1/stats", GetStatsAsync)
            .RequireAuthorization(AuthorizationPolicies.Admin)
            .RequireRateLimiting(RateLimitPolicies.PerClient)
            .WithTags("Statistics")
            .WithName("GetDatasetStats")
            .WithSummary("Summary statistics for the loaded dataset.")
            .WithDescription("Requires the `admin` role. A `reader` token receives 403.")
            .Produces<StatsResponse>(StatusCodes.Status200OK)
            .ProducesProblem(StatusCodes.Status401Unauthorized)
            .ProducesProblem(StatusCodes.Status403Forbidden)
            .ProducesProblem(StatusCodes.Status502BadGateway);

        return app;
    }

    /// <summary>Search movies with a natural language description.</summary>
    /// <param name="q">
    /// Natural language description of the wanted movie. Required. Example:
    /// <c>action movies from the 90s with high IMDB ratings</c>.
    /// </param>
    /// <param name="topK">Number of results, from 1 to 50. Defaults to 10.</param>
    /// <param name="genre">Exact genre. Call <c>/api/v1/movies/genres</c> for the accepted values.</param>
    /// <param name="minImdbRating">Lowest acceptable IMDB rating, from 0 to 10.</param>
    /// <param name="mpaaRating">Exact MPAA certificate, for example <c>PG-13</c>.</param>
    /// <param name="decade">Decade written as its first year, for example <c>1990</c>.</param>
    /// <param name="service">Search service.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>The matching movies, ordered by similarity.</returns>
    private static async Task<Ok<SearchResponse>> SearchAsync(
        [FromQuery(Name = "q")] string? q,
        [FromQuery(Name = "top_k")] int? topK,
        [FromQuery(Name = "genre")] string? genre,
        [FromQuery(Name = "min_imdb_rating")] double? minImdbRating,
        [FromQuery(Name = "mpaa_rating")] string? mpaaRating,
        [FromQuery(Name = "decade")] int? decade,
        IMovieSearchService service,
        CancellationToken cancellationToken)
    {
        var criteria = MovieSearchCriteria.Create(q, topK, genre, minImdbRating, mpaaRating, decade);

        var started = Stopwatch.GetTimestamp();
        var result = await service.SearchAsync(criteria, cancellationToken).ConfigureAwait(false);
        var elapsed = Stopwatch.GetElapsedTime(started).TotalMilliseconds;

        return TypedResults.Ok(new SearchResponse(
            criteria.Query,
            result.Count,
            criteria.TopK,
            new SearchFilters(criteria.Genre, criteria.MinimumImdbRating, criteria.MpaaRating, criteria.Decade),
            result.FromCache,
            Math.Round(elapsed, 2),
            result.Movies.Select(MovieResponse.From).ToList()));
    }

    /// <summary>Fetch one movie by its identifier.</summary>
    /// <param name="id">Movie identifier.</param>
    /// <param name="service">Search service.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>The movie, or 404 when the identifier is unknown.</returns>
    private static async Task<Results<Ok<MovieResponse>, NotFound<ProblemDetails>>> GetByIdAsync(
        Guid id,
        IMovieSearchService service,
        CancellationToken cancellationToken)
    {
        var movie = await service.GetByIdAsync(id, cancellationToken).ConfigureAwait(false);
        return movie is null
            ? TypedResults.NotFound(NotFoundProblem(id))
            : TypedResults.Ok(MovieResponse.From(movie));
    }

    /// <summary>Fetch the movies closest in meaning to one movie.</summary>
    /// <param name="id">Movie identifier.</param>
    /// <param name="topK">Number of neighbours, from 1 to 50. Defaults to 5.</param>
    /// <param name="service">Search service.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>The neighbours, or 404 when the identifier is unknown.</returns>
    private static async Task<Results<Ok<SimilarMoviesResponse>, NotFound<ProblemDetails>>> GetSimilarAsync(
        Guid id,
        [FromQuery(Name = "top_k")] int? topK,
        IMovieSearchService service,
        CancellationToken cancellationToken)
    {
        try
        {
            var neighbours = await service
                .GetSimilarAsync(id, topK ?? 5, cancellationToken)
                .ConfigureAwait(false);
            return TypedResults.Ok(new SimilarMoviesResponse(
                id,
                neighbours.Count,
                neighbours.Select(MovieResponse.From).ToList()));
        }
        catch (MovieNotFoundException)
        {
            return TypedResults.NotFound(NotFoundProblem(id));
        }
    }

    /// <summary>List every genre in the catalogue.</summary>
    /// <param name="service">Search service.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>The genre names, most common first.</returns>
    private static async Task<Ok<GenresResponse>> GetGenresAsync(
        IMovieSearchService service,
        CancellationToken cancellationToken)
    {
        var genres = await service.GetGenresAsync(cancellationToken).ConfigureAwait(false);
        return TypedResults.Ok(new GenresResponse(genres.Count, genres));
    }

    /// <summary>Summary statistics for the loaded dataset.</summary>
    /// <param name="service">Search service.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>The statistics.</returns>
    private static async Task<Ok<StatsResponse>> GetStatsAsync(
        IMovieSearchService service,
        CancellationToken cancellationToken)
    {
        DatasetStatistics statistics = await service
            .GetStatisticsAsync(cancellationToken)
            .ConfigureAwait(false);
        return TypedResults.Ok(StatsResponse.From(statistics));
    }

    private static ProblemDetails NotFoundProblem(Guid id) => new()
    {
        Status = StatusCodes.Status404NotFound,
        Title = "Movie not found",
        Detail = $"No movie has the id {id}.",
        Type = "https://datatracker.ietf.org/doc/html/rfc9110#section-15.5.5",
    };
}

/// <summary>Names of the authorization policies.</summary>
internal static class AuthorizationPolicies
{
    /// <summary>Requires the reader role or the admin role.</summary>
    public const string Reader = "reader-or-admin";

    /// <summary>Requires the admin role.</summary>
    public const string Admin = Roles.Admin;
}
