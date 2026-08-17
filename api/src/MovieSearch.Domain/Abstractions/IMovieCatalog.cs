using MovieSearch.Domain.Entities;
using MovieSearch.Domain.ValueObjects;

namespace MovieSearch.Domain.Abstractions;

/// <summary>
/// The catalogue of movies, as the domain sees it.
/// </summary>
/// <remarks>
/// This is the port. The domain states what it needs; it does not state that the
/// answer arrives over MCP, or over anything else. The MCP implementation lives
/// in the infrastructure layer, and a test substitutes its own implementation
/// without a server.
/// </remarks>
public interface IMovieCatalog
{
    /// <summary>Search the catalogue by meaning, narrowed by the metadata filters.</summary>
    /// <param name="criteria">Validated search inputs.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>Movies ordered by similarity, best first. Empty when nothing matches.</returns>
    Task<IReadOnlyList<Movie>> SearchAsync(
        MovieSearchCriteria criteria,
        CancellationToken cancellationToken);

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
    /// <returns>Neighbours ordered by similarity. The movie itself is never included.</returns>
    Task<IReadOnlyList<Movie>> GetSimilarAsync(Guid id, int topK, CancellationToken cancellationToken);

    /// <summary>List every genre the catalogue holds.</summary>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>Genre names, most common first.</returns>
    Task<IReadOnlyList<string>> GetGenresAsync(CancellationToken cancellationToken);

    /// <summary>Fetch the summary statistics of the catalogue.</summary>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>The statistics.</returns>
    Task<DatasetStatistics> GetStatisticsAsync(CancellationToken cancellationToken);

    /// <summary>Check whether the catalogue can answer right now.</summary>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>True when the catalogue is reachable and usable.</returns>
    Task<bool> IsAvailableAsync(CancellationToken cancellationToken);
}
