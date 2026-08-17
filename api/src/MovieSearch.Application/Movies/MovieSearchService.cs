using System.Diagnostics;
using Microsoft.Extensions.Logging;
using MovieSearch.Domain.Abstractions;
using MovieSearch.Domain.Entities;
using MovieSearch.Domain.Exceptions;
using MovieSearch.Domain.ValueObjects;

namespace MovieSearch.Application.Movies;

/// <summary>
/// Runs the use cases against the catalogue port.
/// </summary>
/// <remarks>
/// The layer is thin on purpose. Its job is to own the rules that are neither
/// HTTP concerns nor catalogue concerns: bounding <c>topK</c> for the neighbour
/// lookup, turning "nothing found" into an empty result rather than an error,
/// and putting the outcome of every call on the current trace.
/// </remarks>
/// <param name="catalog">The catalogue port.</param>
/// <param name="logger">Logger.</param>
public sealed class MovieSearchService(IMovieCatalog catalog, ILogger<MovieSearchService> logger)
    : IMovieSearchService
{
    /// <inheritdoc />
    public async Task<MovieSearchResult> SearchAsync(
        MovieSearchCriteria criteria,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(criteria);

        var movies = await catalog.SearchAsync(criteria, cancellationToken).ConfigureAwait(false);

        Activity.Current?.SetTag("movie_search.result_count", movies.Count);
        Activity.Current?.SetTag("movie_search.top_k", criteria.TopK);
        logger.LogInformation(
            "Search returned {ResultCount} movies for query {Query} with filters genre={Genre} " +
            "decade={Decade} mpaa={MpaaRating} minImdb={MinimumImdbRating}",
            movies.Count,
            criteria.Query,
            criteria.Genre,
            criteria.Decade,
            criteria.MpaaRating,
            criteria.MinimumImdbRating);

        return new MovieSearchResult(criteria, movies);
    }

    /// <inheritdoc />
    public Task<Movie?> GetByIdAsync(Guid id, CancellationToken cancellationToken)
    {
        if (id == Guid.Empty)
        {
            throw new InvalidSearchCriteriaException("id", "A movie id is required.");
        }

        return catalog.GetByIdAsync(id, cancellationToken);
    }

    /// <inheritdoc />
    public Task<Movie?> GetByTitleAsync(string title, CancellationToken cancellationToken)
    {
        var trimmed = title?.Trim();
        if (string.IsNullOrEmpty(trimmed))
        {
            throw new InvalidSearchCriteriaException("title", "A title is required.");
        }

        return catalog.GetByTitleAsync(trimmed, cancellationToken);
    }

    /// <inheritdoc />
    public Task<IReadOnlyList<Movie>> GetSimilarAsync(
        Guid id,
        int topK,
        CancellationToken cancellationToken)
    {
        if (id == Guid.Empty)
        {
            throw new InvalidSearchCriteriaException("id", "A movie id is required.");
        }

        if (topK is < MovieSearchCriteria.MinTopK or > MovieSearchCriteria.MaxTopK)
        {
            throw new InvalidSearchCriteriaException(
                "top_k",
                $"top_k must be between {MovieSearchCriteria.MinTopK} and {MovieSearchCriteria.MaxTopK}.");
        }

        return catalog.GetSimilarAsync(id, topK, cancellationToken);
    }

    /// <inheritdoc />
    public Task<IReadOnlyList<string>> GetGenresAsync(CancellationToken cancellationToken) =>
        catalog.GetGenresAsync(cancellationToken);

    /// <inheritdoc />
    public Task<DatasetStatistics> GetStatisticsAsync(CancellationToken cancellationToken) =>
        catalog.GetStatisticsAsync(cancellationToken);
}
