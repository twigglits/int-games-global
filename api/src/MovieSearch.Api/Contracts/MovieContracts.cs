using MovieSearch.Domain.Entities;

namespace MovieSearch.Api.Contracts;

/// <summary>One movie in an API response.</summary>
/// <param name="Id">Stable identifier. Pass it to the similar-movies endpoint.</param>
/// <param name="Title">Movie title.</param>
/// <param name="ReleaseDate">Release date, when the source recorded one.</param>
/// <param name="ReleaseYear">Release year, when the source recorded one.</param>
/// <param name="Decade">Decade written as its first year, for example 1990.</param>
/// <param name="MajorGenre">Primary genre.</param>
/// <param name="CreativeType">Creative type of the story.</param>
/// <param name="Source">Source material the film came from.</param>
/// <param name="MpaaRating">MPAA certificate.</param>
/// <param name="Director">Director.</param>
/// <param name="Distributor">Distributor.</param>
/// <param name="RunningTimeMin">Runtime in minutes.</param>
/// <param name="ProductionBudget">Production budget in US dollars.</param>
/// <param name="UsGross">US box office in US dollars.</param>
/// <param name="WorldwideGross">Worldwide box office in US dollars.</param>
/// <param name="ImdbRating">IMDB rating from 0 to 10.</param>
/// <param name="ImdbVotes">Number of IMDB votes.</param>
/// <param name="RtRating">Rotten Tomatoes score from 0 to 100.</param>
/// <param name="BudgetTier">Budget bucket: micro, low, mid, high or blockbuster.</param>
/// <param name="BlockbusterFlag">True when the film cleared both blockbuster bars.</param>
/// <param name="RatingScoreDelta">
/// IMDB rating times ten minus the Rotten Tomatoes score. Positive means
/// audiences scored the film above critics.
/// </param>
/// <param name="ImputedFields">
/// Fields the data pipeline filled in rather than read from the source dataset.
/// Use it to exclude estimated values from any analysis.
/// </param>
/// <param name="Similarity">
/// Cosine similarity to the search query, from 0.0 to 1.0. Null when the movie
/// was fetched by id or title rather than by a search.
/// </param>
public sealed record MovieResponse(
    Guid Id,
    string Title,
    DateOnly? ReleaseDate,
    int? ReleaseYear,
    int? Decade,
    string? MajorGenre,
    string? CreativeType,
    string? Source,
    string? MpaaRating,
    string? Director,
    string? Distributor,
    int? RunningTimeMin,
    long? ProductionBudget,
    long? UsGross,
    long? WorldwideGross,
    double? ImdbRating,
    int? ImdbVotes,
    int? RtRating,
    string? BudgetTier,
    bool? BlockbusterFlag,
    double? RatingScoreDelta,
    IReadOnlyList<string> ImputedFields,
    double? Similarity)
{
    /// <summary>Build a response from a domain movie.</summary>
    /// <param name="movie">The domain movie.</param>
    /// <returns>The response shape.</returns>
    public static MovieResponse From(Movie movie)
    {
        ArgumentNullException.ThrowIfNull(movie);
        return new MovieResponse(
            movie.Id,
            movie.Title,
            movie.ReleaseDate,
            movie.ReleaseYear,
            movie.Decade,
            movie.MajorGenre,
            movie.CreativeType,
            movie.Source,
            movie.MpaaRating,
            movie.Director,
            movie.Distributor,
            movie.RunningTimeMinutes,
            movie.ProductionBudget,
            movie.UsGross,
            movie.WorldwideGross,
            movie.ImdbRating,
            movie.ImdbVotes,
            movie.RottenTomatoesRating,
            movie.BudgetTier,
            movie.IsBlockbuster,
            movie.RatingScoreDelta,
            movie.ImputedFields,
            movie.Similarity);
    }
}

/// <summary>The filters that were applied to a search.</summary>
/// <param name="Genre">Genre filter, or null.</param>
/// <param name="MinImdbRating">Minimum IMDB rating filter, or null.</param>
/// <param name="MpaaRating">MPAA certificate filter, or null.</param>
/// <param name="Decade">Decade filter, or null.</param>
public sealed record SearchFilters(
    string? Genre,
    double? MinImdbRating,
    string? MpaaRating,
    int? Decade);

/// <summary>The answer to a movie search.</summary>
/// <param name="Query">The query that was run, after trimming.</param>
/// <param name="Count">Number of results returned.</param>
/// <param name="TopK">Number of results that were asked for.</param>
/// <param name="Filters">The filters that were applied.</param>
/// <param name="Cached">True when the answer came from the response cache.</param>
/// <param name="TookMs">Server-side time in milliseconds.</param>
/// <param name="Results">Movies ordered by similarity, best first.</param>
public sealed record SearchResponse(
    string Query,
    int Count,
    int TopK,
    SearchFilters Filters,
    bool Cached,
    double TookMs,
    IReadOnlyList<MovieResponse> Results);

/// <summary>The list of genres the catalogue holds.</summary>
/// <param name="Count">Number of distinct genres.</param>
/// <param name="Genres">Genre names, most common first.</param>
public sealed record GenresResponse(int Count, IReadOnlyList<string> Genres);

/// <summary>The neighbours of one movie.</summary>
/// <param name="MovieId">The movie the neighbours were computed for.</param>
/// <param name="Count">Number of neighbours returned.</param>
/// <param name="Results">Neighbours ordered by similarity, best first.</param>
public sealed record SimilarMoviesResponse(
    Guid MovieId,
    int Count,
    IReadOnlyList<MovieResponse> Results);

/// <summary>How many movies carry one genre.</summary>
/// <param name="Genre">Genre name.</param>
/// <param name="Count">Number of movies.</param>
public sealed record GenreCountResponse(string Genre, int Count);

/// <summary>How many movies fall in one decade.</summary>
/// <param name="Decade">Decade written as its first year.</param>
/// <param name="Count">Number of movies.</param>
public sealed record DecadeCountResponse(int Decade, int Count);

/// <summary>Summary statistics for the loaded dataset.</summary>
/// <param name="TotalMovies">Rows in the catalogue.</param>
/// <param name="MoviesWithEmbeddings">Rows that carry a vector and are searchable.</param>
/// <param name="DistinctGenres">Number of distinct genres.</param>
/// <param name="DistinctDirectors">Number of distinct directors.</param>
/// <param name="DistinctDistributors">Number of distinct distributors.</param>
/// <param name="EarliestReleaseYear">Lowest release year.</param>
/// <param name="LatestReleaseYear">Highest release year.</param>
/// <param name="AverageImdbRating">Mean IMDB rating.</param>
/// <param name="AverageRtRating">Mean Rotten Tomatoes score.</param>
/// <param name="MedianProductionBudget">Median budget in US dollars.</param>
/// <param name="TotalWorldwideGross">Sum of the known worldwide box office.</param>
/// <param name="MoviesPerGenre">Row count per genre, largest first.</param>
/// <param name="MoviesPerDecade">Row count per decade, oldest first.</param>
/// <param name="EmbeddingModel">Model that produced the vectors.</param>
/// <param name="EmbeddingDimension">Width of the stored vectors.</param>
/// <param name="PipelineVersion">Version of the pipeline that last wrote a row.</param>
/// <param name="LastUpdated">Newest update timestamp in the catalogue.</param>
public sealed record StatsResponse(
    int TotalMovies,
    int MoviesWithEmbeddings,
    int DistinctGenres,
    int DistinctDirectors,
    int DistinctDistributors,
    int? EarliestReleaseYear,
    int? LatestReleaseYear,
    double? AverageImdbRating,
    double? AverageRtRating,
    long? MedianProductionBudget,
    long? TotalWorldwideGross,
    IReadOnlyList<GenreCountResponse> MoviesPerGenre,
    IReadOnlyList<DecadeCountResponse> MoviesPerDecade,
    string? EmbeddingModel,
    int EmbeddingDimension,
    string? PipelineVersion,
    DateTimeOffset? LastUpdated)
{
    /// <summary>Build a response from the domain statistics.</summary>
    /// <param name="statistics">The domain statistics.</param>
    /// <returns>The response shape.</returns>
    public static StatsResponse From(DatasetStatistics statistics)
    {
        ArgumentNullException.ThrowIfNull(statistics);
        return new StatsResponse(
            statistics.TotalMovies,
            statistics.MoviesWithEmbeddings,
            statistics.DistinctGenres,
            statistics.DistinctDirectors,
            statistics.DistinctDistributors,
            statistics.EarliestReleaseYear,
            statistics.LatestReleaseYear,
            statistics.AverageImdbRating,
            statistics.AverageRottenTomatoesRating,
            statistics.MedianProductionBudget,
            statistics.TotalWorldwideGross,
            statistics.MoviesPerGenre.Select(g => new GenreCountResponse(g.Genre, g.Count)).ToList(),
            statistics.MoviesPerDecade.Select(d => new DecadeCountResponse(d.Decade, d.Count)).ToList(),
            statistics.EmbeddingModel,
            statistics.EmbeddingDimension,
            statistics.PipelineVersion,
            statistics.LastUpdated);
    }
}
