namespace MovieSearch.Domain.Entities;

/// <summary>How many movies carry one genre.</summary>
/// <param name="Genre">Genre name.</param>
/// <param name="Count">Number of movies.</param>
public sealed record GenreCount(string Genre, int Count);

/// <summary>How many movies fall in one decade.</summary>
/// <param name="Decade">Decade written as its first year.</param>
/// <param name="Count">Number of movies.</param>
public sealed record DecadeCount(int Decade, int Count);

/// <summary>Summary statistics for the loaded dataset.</summary>
/// <param name="TotalMovies">Rows in the catalogue.</param>
/// <param name="MoviesWithEmbeddings">Rows that carry a vector and are searchable.</param>
/// <param name="DistinctGenres">Number of distinct genres.</param>
/// <param name="DistinctDirectors">Number of distinct directors.</param>
/// <param name="DistinctDistributors">Number of distinct distributors.</param>
/// <param name="EarliestReleaseYear">Lowest release year.</param>
/// <param name="LatestReleaseYear">Highest release year.</param>
/// <param name="AverageImdbRating">Mean IMDB rating.</param>
/// <param name="AverageRottenTomatoesRating">Mean Rotten Tomatoes score.</param>
/// <param name="MedianProductionBudget">Median budget in US dollars.</param>
/// <param name="TotalWorldwideGross">Sum of the known worldwide box office.</param>
/// <param name="MoviesPerGenre">Row count per genre, largest first.</param>
/// <param name="MoviesPerDecade">Row count per decade, oldest first.</param>
/// <param name="EmbeddingModel">Model that produced the vectors.</param>
/// <param name="EmbeddingDimension">Width of the stored vectors.</param>
/// <param name="PipelineVersion">Version of the pipeline that last wrote a row.</param>
/// <param name="LastUpdated">Newest update timestamp in the catalogue.</param>
public sealed record DatasetStatistics(
    int TotalMovies,
    int MoviesWithEmbeddings,
    int DistinctGenres,
    int DistinctDirectors,
    int DistinctDistributors,
    int? EarliestReleaseYear,
    int? LatestReleaseYear,
    double? AverageImdbRating,
    double? AverageRottenTomatoesRating,
    long? MedianProductionBudget,
    long? TotalWorldwideGross,
    IReadOnlyList<GenreCount> MoviesPerGenre,
    IReadOnlyList<DecadeCount> MoviesPerDecade,
    string? EmbeddingModel,
    int EmbeddingDimension,
    string? PipelineVersion,
    DateTimeOffset? LastUpdated);
