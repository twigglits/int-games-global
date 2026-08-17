using MovieSearch.Domain.Abstractions;
using MovieSearch.Domain.Entities;
using MovieSearch.Domain.Exceptions;
using MovieSearch.Domain.ValueObjects;

namespace MovieSearch.Tests.Fakes;

/// <summary>
/// A catalogue stand-in. It records what it was asked and returns what the test
/// tells it to, so every layer above it runs its real code.
/// </summary>
public sealed class FakeMovieCatalog : IMovieCatalog
{
    public static readonly Guid TerminatorId = new("8267e750-d59b-4259-a9f6-4025e0d78565");
    public static readonly Guid AliensId = new("0f7c1f9e-2a1b-4a3c-9d55-1b2c3d4e5f60");

    public List<MovieSearchCriteria> SearchCalls { get; } = [];

    public int SearchCallCount => SearchCalls.Count;

    public int GenreCallCount { get; private set; }

    public int StatsCallCount { get; private set; }

    public List<Movie> SearchResults { get; set; } = [Movie(TerminatorId, "The Terminator", 0.81)];

    public Movie? MovieById { get; set; } = Movie(TerminatorId, "The Terminator", null);

    public Movie? MovieByTitle { get; set; } = Movie(TerminatorId, "The Terminator", null);

    public List<Movie>? SimilarResults { get; set; } = [Movie(AliensId, "Aliens", 0.86)];

    public List<string> Genres { get; set; } = ["Drama", "Comedy", "Action"];

    public bool Available { get; set; } = true;

    public Exception? SearchThrows { get; set; }

    public static Movie Movie(Guid id, string title, double? similarity) => new(
        id,
        title,
        new DateOnly(1984, 10, 26),
        1984,
        1980,
        "Action",
        "Science Fiction",
        "Original Screenplay",
        "R",
        "James Cameron",
        "Orion",
        108,
        6_400_000,
        38_400_000,
        78_300_000,
        8.1,
        300_000,
        100,
        "low",
        false,
        -19.0,
        [],
        similarity);

    public Task<IReadOnlyList<Movie>> SearchAsync(
        MovieSearchCriteria criteria,
        CancellationToken cancellationToken)
    {
        SearchCalls.Add(criteria);
        if (SearchThrows is not null)
        {
            throw SearchThrows;
        }

        return Task.FromResult<IReadOnlyList<Movie>>(SearchResults);
    }

    public Task<Movie?> GetByIdAsync(Guid id, CancellationToken cancellationToken) =>
        Task.FromResult(MovieById);

    public Task<Movie?> GetByTitleAsync(string title, CancellationToken cancellationToken) =>
        Task.FromResult(MovieByTitle);

    public Task<IReadOnlyList<Movie>> GetSimilarAsync(
        Guid id,
        int topK,
        CancellationToken cancellationToken) =>
        SimilarResults is null
            ? throw new MovieNotFoundException(id)
            : Task.FromResult<IReadOnlyList<Movie>>(SimilarResults.Take(topK).ToList());

    public Task<IReadOnlyList<string>> GetGenresAsync(CancellationToken cancellationToken)
    {
        GenreCallCount++;
        return Task.FromResult<IReadOnlyList<string>>(Genres);
    }

    public Task<DatasetStatistics> GetStatisticsAsync(CancellationToken cancellationToken)
    {
        StatsCallCount++;
        return Task.FromResult(new DatasetStatistics(
            3200,
            3200,
            13,
            800,
            175,
            1915,
            2011,
            6.28,
            52.4,
            20_000_000,
            250_000_000_000,
            [new GenreCount("Drama", 789)],
            [new DecadeCount(1990, 769)],
            "BAAI/bge-base-en-v1.5",
            768,
            "1.0.0",
            DateTimeOffset.UnixEpoch));
    }

    public Task<bool> IsAvailableAsync(CancellationToken cancellationToken) => Task.FromResult(Available);
}
