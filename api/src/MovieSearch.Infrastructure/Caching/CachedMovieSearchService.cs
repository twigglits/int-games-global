using System.Diagnostics;
using System.Diagnostics.Metrics;
using Microsoft.Extensions.Caching.Memory;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using MovieSearch.Application.Movies;
using MovieSearch.Domain.Entities;
using MovieSearch.Domain.ValueObjects;
using MovieSearch.Infrastructure.Configuration;

namespace MovieSearch.Infrastructure.Caching;

/// <summary>
/// Serves repeated identical queries from memory.
/// </summary>
/// <remarks>
/// The decorator sits around the whole use case rather than inside it, so the
/// service it wraps has no cache code at all and can be tested without one.
///
/// What is cached and why:
/// <list type="bullet">
///   <item>A search costs an embedding call plus a vector scan. Repeating an
///   identical query inside the time to live cannot produce a different answer,
///   because the catalogue only changes when the pipeline runs.</item>
///   <item>The genre list and the dataset statistics change even less often, and
///   both are read on nearly every page load, so they are cached as well.</item>
///   <item>A lookup by identifier is a single indexed read. Caching it would add
///   memory pressure for no measurable gain, so it passes straight through.</item>
/// </list>
/// The cache key comes from <see cref="MovieSearchCriteria.ToCacheKey"/>, which
/// normalises casing and padding. It carries no user identity, because the
/// answer does not depend on who asks: authorization decides whether the call is
/// allowed, not what it returns.
/// </remarks>
/// <param name="inner">The service being decorated.</param>
/// <param name="cache">Backing memory cache.</param>
/// <param name="options">Cache settings.</param>
/// <param name="logger">Logger.</param>
public sealed class CachedMovieSearchService(
    IMovieSearchService inner,
    IMemoryCache cache,
    IOptions<CacheOptions> options,
    ILogger<CachedMovieSearchService> logger) : IMovieSearchService
{
    private const string GenresKey = "genres";
    private const string StatsKey = "stats";

    private static readonly Meter Meter = new("MovieSearch.Cache");

    private static readonly Counter<long> Lookups = Meter.CreateCounter<long>(
        "movie_search.cache.lookups",
        description: "Response cache lookups, by outcome.");

    private readonly CacheOptions _options = options.Value;

    /// <inheritdoc />
    public Task<MovieSearchResult> SearchAsync(
        MovieSearchCriteria criteria,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(criteria);

        if (!_options.Enabled)
        {
            return inner.SearchAsync(criteria, cancellationToken);
        }

        var key = criteria.ToCacheKey();
        if (cache.TryGetValue(key, out IReadOnlyList<Movie>? cached) && cached is not null)
        {
            Record(hit: true, "search");
            logger.LogDebug("Search cache hit for {CacheKey}", key);
            return Task.FromResult(new MovieSearchResult(criteria, cached, FromCache: true));
        }

        Record(hit: false, "search");
        return SearchAndCacheAsync(criteria, key, cancellationToken);
    }

    /// <inheritdoc />
    public Task<Movie?> GetByIdAsync(Guid id, CancellationToken cancellationToken) =>
        inner.GetByIdAsync(id, cancellationToken);

    /// <inheritdoc />
    public Task<Movie?> GetByTitleAsync(string title, CancellationToken cancellationToken) =>
        inner.GetByTitleAsync(title, cancellationToken);

    /// <inheritdoc />
    public Task<IReadOnlyList<Movie>> GetSimilarAsync(
        Guid id,
        int topK,
        CancellationToken cancellationToken) =>
        inner.GetSimilarAsync(id, topK, cancellationToken);

    /// <inheritdoc />
    public Task<IReadOnlyList<string>> GetGenresAsync(CancellationToken cancellationToken) =>
        GetOrCreateAsync(GenresKey, () => inner.GetGenresAsync(cancellationToken));

    /// <inheritdoc />
    public Task<DatasetStatistics> GetStatisticsAsync(CancellationToken cancellationToken) =>
        GetOrCreateAsync(StatsKey, () => inner.GetStatisticsAsync(cancellationToken));

    private static void Record(bool hit, string operation)
    {
        var tags = new TagList { { "outcome", hit ? "hit" : "miss" }, { "operation", operation } };
        Lookups.Add(1, tags);
        Activity.Current?.SetTag("cache.hit", hit);
    }

    private async Task<MovieSearchResult> SearchAndCacheAsync(
        MovieSearchCriteria criteria,
        string key,
        CancellationToken cancellationToken)
    {
        var result = await inner.SearchAsync(criteria, cancellationToken).ConfigureAwait(false);
        cache.Set(key, result.Movies, CacheEntry(result.Movies.Count + 1));
        return result;
    }

    private async Task<T> GetOrCreateAsync<T>(string key, Func<Task<T>> factory)
    {
        if (!_options.Enabled)
        {
            return await factory().ConfigureAwait(false);
        }

        if (cache.TryGetValue(key, out T? cached) && cached is not null)
        {
            Record(hit: true, key);
            return cached;
        }

        Record(hit: false, key);
        var value = await factory().ConfigureAwait(false);
        cache.Set(key, value, CacheEntry(size: 1));
        return value;
    }

    private MemoryCacheEntryOptions CacheEntry(int size) => new()
    {
        AbsoluteExpirationRelativeToNow = TimeSpan.FromSeconds(_options.TtlSeconds),
        // Size is counted in rows, not entries, so one 50-row search cannot cost
        // the same as one single-row answer.
        Size = size,
    };
}
