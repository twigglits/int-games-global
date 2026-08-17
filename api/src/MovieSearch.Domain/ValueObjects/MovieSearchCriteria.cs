using MovieSearch.Domain.Exceptions;

namespace MovieSearch.Domain.ValueObjects;

/// <summary>
/// A validated set of search inputs.
/// </summary>
/// <remarks>
/// The type has a private constructor, so an instance can only come from
/// <see cref="Create"/>. Every layer above can therefore treat a
/// <see cref="MovieSearchCriteria"/> as already checked, and the bounds live in
/// one place rather than being repeated in the endpoint, the cache key and the
/// MCP client.
/// </remarks>
public sealed record MovieSearchCriteria
{
    /// <summary>Smallest number of results a caller may ask for.</summary>
    public const int MinTopK = 1;

    /// <summary>Largest number of results a caller may ask for.</summary>
    public const int MaxTopK = 50;

    /// <summary>Number of results used when the caller does not say.</summary>
    public const int DefaultTopK = 10;

    /// <summary>Longest accepted query string.</summary>
    public const int MaxQueryLength = 1000;

    /// <summary>Earliest decade the catalogue can hold.</summary>
    public const int MinDecade = 1900;

    /// <summary>Latest decade the catalogue can hold.</summary>
    public const int MaxDecade = 2100;

    private MovieSearchCriteria(
        string query,
        int topK,
        string? genre,
        double? minimumImdbRating,
        string? mpaaRating,
        int? decade)
    {
        Query = query;
        TopK = topK;
        Genre = genre;
        MinimumImdbRating = minimumImdbRating;
        MpaaRating = mpaaRating;
        Decade = decade;
    }

    /// <summary>Natural language description of the wanted movie.</summary>
    public string Query { get; }

    /// <summary>Number of results to return.</summary>
    public int TopK { get; }

    /// <summary>Exact genre to filter on, or null for no genre filter.</summary>
    public string? Genre { get; }

    /// <summary>Lowest acceptable IMDB rating, or null for no rating filter.</summary>
    public double? MinimumImdbRating { get; }

    /// <summary>Exact MPAA certificate to filter on, or null for no certificate filter.</summary>
    public string? MpaaRating { get; }

    /// <summary>Decade written as its first year, or null for no decade filter.</summary>
    public int? Decade { get; }

    /// <summary>Validate raw inputs and build the criteria.</summary>
    /// <param name="query">Natural language description. Required.</param>
    /// <param name="topK">Number of results. Null means <see cref="DefaultTopK"/>.</param>
    /// <param name="genre">Exact genre, or null.</param>
    /// <param name="minimumImdbRating">Lowest IMDB rating, or null.</param>
    /// <param name="mpaaRating">Exact MPAA certificate, or null.</param>
    /// <param name="decade">Decade written as its first year, or null.</param>
    /// <returns>Validated criteria.</returns>
    /// <exception cref="InvalidSearchCriteriaException">When any input is out of range.</exception>
    public static MovieSearchCriteria Create(
        string? query,
        int? topK = null,
        string? genre = null,
        double? minimumImdbRating = null,
        string? mpaaRating = null,
        int? decade = null)
    {
        var trimmedQuery = query?.Trim();
        if (string.IsNullOrEmpty(trimmedQuery))
        {
            throw new InvalidSearchCriteriaException("q", "A search query is required.");
        }

        if (trimmedQuery.Length > MaxQueryLength)
        {
            throw new InvalidSearchCriteriaException(
                "q",
                $"A search query may be at most {MaxQueryLength} characters long.");
        }

        var effectiveTopK = topK ?? DefaultTopK;
        if (effectiveTopK is < MinTopK or > MaxTopK)
        {
            throw new InvalidSearchCriteriaException(
                "top_k",
                $"top_k must be between {MinTopK} and {MaxTopK}.");
        }

        if (minimumImdbRating is < 0 or > 10)
        {
            throw new InvalidSearchCriteriaException(
                "min_imdb_rating",
                "min_imdb_rating must be between 0 and 10.");
        }

        if (decade is not null && (decade < MinDecade || decade > MaxDecade))
        {
            throw new InvalidSearchCriteriaException(
                "decade",
                $"decade must be between {MinDecade} and {MaxDecade}.");
        }

        if (decade is not null && decade % 10 != 0)
        {
            throw new InvalidSearchCriteriaException(
                "decade",
                "decade must be the first year of a decade, for example 1990.");
        }

        return new MovieSearchCriteria(
            trimmedQuery,
            effectiveTopK,
            NullIfBlank(genre),
            minimumImdbRating,
            NullIfBlank(mpaaRating),
            decade);
    }

    /// <summary>
    /// A stable key for these criteria. Two requests that differ only in the
    /// casing or the padding of a filter produce the same key and share one
    /// cache entry.
    /// </summary>
    /// <returns>The cache key.</returns>
    public string ToCacheKey() => string.Join(
        '|',
        "search",
        Query.ToLowerInvariant(),
        TopK.ToString(System.Globalization.CultureInfo.InvariantCulture),
        Genre?.ToLowerInvariant() ?? "-",
        MinimumImdbRating?.ToString("0.0", System.Globalization.CultureInfo.InvariantCulture) ?? "-",
        MpaaRating?.ToLowerInvariant() ?? "-",
        Decade?.ToString(System.Globalization.CultureInfo.InvariantCulture) ?? "-");

    private static string? NullIfBlank(string? value)
    {
        var trimmed = value?.Trim();
        return string.IsNullOrEmpty(trimmed) ? null : trimmed;
    }
}
