using MovieSearch.Domain.Entities;
using MovieSearch.Domain.ValueObjects;

namespace MovieSearch.Application.Movies;

/// <summary>
/// The use cases the API exposes.
/// </summary>
/// <remarks>
/// The interface exists so that caching can be added as a decorator around the
/// whole use case rather than inside it. The caching decorator lives in the
/// infrastructure layer and implements this same interface, so neither the
/// endpoints nor the service itself know whether a result was cached.
/// </remarks>
public interface IMovieSearchService
{
    /// <summary>Search the catalogue by meaning.</summary>
    /// <param name="criteria">Validated search inputs.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>The result of the search.</returns>
    Task<MovieSearchResult> SearchAsync(MovieSearchCriteria criteria, CancellationToken cancellationToken);

    /// <summary>Fetch one movie by identifier.</summary>
    /// <param name="id">Movie identifier.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>The movie, or null when the identifier is unknown.</returns>
    Task<Movie?> GetByIdAsync(Guid id, CancellationToken cancellationToken);

    /// <summary>Fetch one movie by exact or approximate title.</summary>
    /// <param name="title">Title to look for.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>The movie, or null when nothing is close enough.</returns>
    Task<Movie?> GetByTitleAsync(string title, CancellationToken cancellationToken);

    /// <summary>Fetch the movies closest in meaning to one movie.</summary>
    /// <param name="id">Movie identifier.</param>
    /// <param name="topK">How many neighbours to return.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>The neighbours, ordered by similarity.</returns>
    Task<IReadOnlyList<Movie>> GetSimilarAsync(Guid id, int topK, CancellationToken cancellationToken);

    /// <summary>List every genre the catalogue holds.</summary>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>Genre names, most common first.</returns>
    Task<IReadOnlyList<string>> GetGenresAsync(CancellationToken cancellationToken);

    /// <summary>Fetch the summary statistics of the catalogue.</summary>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>The statistics.</returns>
    Task<DatasetStatistics> GetStatisticsAsync(CancellationToken cancellationToken);
}

/// <summary>The outcome of one search.</summary>
/// <param name="Criteria">The criteria that produced the result.</param>
/// <param name="Movies">Movies ordered by similarity, best first.</param>
/// <param name="FromCache">True when the result was served from the response cache.</param>
public sealed record MovieSearchResult(
    MovieSearchCriteria Criteria,
    IReadOnlyList<Movie> Movies,
    bool FromCache = false)
{
    /// <summary>Number of movies returned.</summary>
    public int Count => Movies.Count;
}
