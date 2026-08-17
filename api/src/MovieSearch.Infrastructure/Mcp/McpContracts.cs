using System.Text.Json;
using System.Text.Json.Serialization;
using MovieSearch.Domain.Entities;

namespace MovieSearch.Infrastructure.Mcp;

/// <summary>
/// Wire shape of the MCP tool results, and the mapping onto the domain entities.
/// </summary>
/// <remarks>
/// FastMCP publishes snake_case JSON. Every property below is named so that the
/// <see cref="JsonNamingPolicy.SnakeCaseLower"/> policy produces the wire name
/// exactly, which is why they read <c>RtRating</c> rather than
/// <c>RottenTomatoesRating</c>. The domain names stay readable because the
/// mapping happens here and nowhere else.
/// </remarks>
internal static class McpJson
{
    /// <summary>Serializer options used for every MCP payload.</summary>
    public static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true,
        NumberHandling = JsonNumberHandling.AllowReadingFromString,
    };
}

/// <summary>
/// FastMCP wraps a non-object tool result in a single <c>result</c> property and
/// marks the schema with <c>x-fastmcp-wrap-result</c>. A tool that returns a
/// model returns that model unwrapped. Both shapes are handled by
/// <see cref="McpResultReader"/>.
/// </summary>
/// <typeparam name="T">Type of the wrapped value.</typeparam>
/// <param name="Result">The wrapped value.</param>
internal sealed record McpWrapped<T>(T? Result);

/// <summary>Wire shape of one movie.</summary>
internal sealed record McpMovie
{
    public Guid Id { get; init; }

    public string Title { get; init; } = string.Empty;

    public DateOnly? ReleaseDate { get; init; }

    public int? ReleaseYear { get; init; }

    public int? Decade { get; init; }

    public string? MajorGenre { get; init; }

    public string? CreativeType { get; init; }

    public string? Source { get; init; }

    public string? MpaaRating { get; init; }

    public string? Director { get; init; }

    public string? Distributor { get; init; }

    public int? RunningTimeMin { get; init; }

    public long? ProductionBudget { get; init; }

    public long? UsGross { get; init; }

    public long? WorldwideGross { get; init; }

    public double? ImdbRating { get; init; }

    public int? ImdbVotes { get; init; }

    public int? RtRating { get; init; }

    public string? BudgetTier { get; init; }

    public bool? BlockbusterFlag { get; init; }

    public double? RatingScoreDelta { get; init; }

    public IReadOnlyList<string>? ImputedFields { get; init; }

    public double? Similarity { get; init; }

    /// <summary>Map the wire shape onto the domain entity.</summary>
    /// <returns>The domain movie.</returns>
    public Movie ToDomain() => new(
        Id,
        Title,
        ReleaseDate,
        ReleaseYear,
        Decade,
        MajorGenre,
        CreativeType,
        Source,
        MpaaRating,
        Director,
        Distributor,
        RunningTimeMin,
        ProductionBudget,
        UsGross,
        WorldwideGross,
        ImdbRating,
        ImdbVotes,
        RtRating,
        BudgetTier,
        BlockbusterFlag,
        RatingScoreDelta,
        ImputedFields ?? [],
        Similarity);
}

/// <summary>Wire shape of one genre count.</summary>
internal sealed record McpGenreCount(string Genre, int Count);

/// <summary>Wire shape of one decade count.</summary>
internal sealed record McpDecadeCount(int Decade, int Count);

/// <summary>Wire shape of the dataset statistics.</summary>
internal sealed record McpDatasetStats
{
    public int TotalMovies { get; init; }

    public int MoviesWithEmbeddings { get; init; }

    public int DistinctGenres { get; init; }

    public int DistinctDirectors { get; init; }

    public int DistinctDistributors { get; init; }

    public int? EarliestReleaseYear { get; init; }

    public int? LatestReleaseYear { get; init; }

    public double? AverageImdbRating { get; init; }

    public double? AverageRtRating { get; init; }

    public long? MedianProductionBudget { get; init; }

    public long? TotalWorldwideGross { get; init; }

    public IReadOnlyList<McpGenreCount>? MoviesPerGenre { get; init; }

    public IReadOnlyList<McpDecadeCount>? MoviesPerDecade { get; init; }

    public string? EmbeddingModel { get; init; }

    public int EmbeddingDimension { get; init; }

    public string? PipelineVersion { get; init; }

    public DateTimeOffset? LastUpdated { get; init; }

    /// <summary>Map the wire shape onto the domain entity.</summary>
    /// <returns>The domain statistics.</returns>
    public DatasetStatistics ToDomain() => new(
        TotalMovies,
        MoviesWithEmbeddings,
        DistinctGenres,
        DistinctDirectors,
        DistinctDistributors,
        EarliestReleaseYear,
        LatestReleaseYear,
        AverageImdbRating,
        AverageRtRating,
        MedianProductionBudget,
        TotalWorldwideGross,
        MoviesPerGenre?.Select(g => new GenreCount(g.Genre, g.Count)).ToList() ?? [],
        MoviesPerDecade?.Select(d => new DecadeCount(d.Decade, d.Count)).ToList() ?? [],
        EmbeddingModel,
        EmbeddingDimension,
        PipelineVersion,
        LastUpdated);
}
