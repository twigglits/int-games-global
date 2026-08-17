namespace MovieSearch.Domain.Entities;

/// <summary>
/// A movie as the platform knows it: the cleaned metadata, the derived features,
/// and the similarity score when the movie came back from a search.
/// </summary>
/// <param name="Id">Stable identifier of the movie.</param>
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
/// <param name="RunningTimeMinutes">Runtime in minutes.</param>
/// <param name="ProductionBudget">Production budget in US dollars.</param>
/// <param name="UsGross">US box office in US dollars.</param>
/// <param name="WorldwideGross">Worldwide box office in US dollars.</param>
/// <param name="ImdbRating">IMDB rating from 0 to 10.</param>
/// <param name="ImdbVotes">Number of IMDB votes.</param>
/// <param name="RottenTomatoesRating">Rotten Tomatoes score from 0 to 100.</param>
/// <param name="BudgetTier">Budget bucket: micro, low, mid, high or blockbuster.</param>
/// <param name="IsBlockbuster">True when the film cleared both blockbuster bars.</param>
/// <param name="RatingScoreDelta">
/// IMDB rating times ten minus the Rotten Tomatoes score. A positive value means
/// audiences scored the film above critics.
/// </param>
/// <param name="ImputedFields">
/// Fields whose value the pipeline filled in rather than read from the source
/// dataset. A caller that needs measured data only can use this to exclude them.
/// </param>
/// <param name="Similarity">
/// Cosine similarity to the search query, from 0.0 to 1.0. Null when the movie
/// was fetched by identifier or title rather than by similarity.
/// </param>
public sealed record Movie(
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
    int? RunningTimeMinutes,
    long? ProductionBudget,
    long? UsGross,
    long? WorldwideGross,
    double? ImdbRating,
    int? ImdbVotes,
    int? RottenTomatoesRating,
    string? BudgetTier,
    bool? IsBlockbuster,
    double? RatingScoreDelta,
    IReadOnlyList<string> ImputedFields,
    double? Similarity);
