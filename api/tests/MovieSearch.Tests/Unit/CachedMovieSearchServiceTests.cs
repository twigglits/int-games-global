using Microsoft.Extensions.Caching.Memory;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using MovieSearch.Application.Movies;
using MovieSearch.Domain.ValueObjects;
using MovieSearch.Infrastructure.Caching;
using MovieSearch.Infrastructure.Configuration;
using MovieSearch.Tests.Fakes;

namespace MovieSearch.Tests.Unit;

public class CachedMovieSearchServiceTests
{
    private static (CachedMovieSearchService Service, FakeMovieCatalog Catalog) Build(
        bool enabled = true,
        int ttlSeconds = 60)
    {
        var catalog = new FakeMovieCatalog();
        var inner = new MovieSearchService(catalog, NullLogger<MovieSearchService>.Instance);
        var cache = new MemoryCache(new MemoryCacheOptions { SizeLimit = 1000 });
        var options = Options.Create(new CacheOptions
        {
            Enabled = enabled,
            TtlSeconds = ttlSeconds,
            SizeLimit = 1000,
        });
        var service = new CachedMovieSearchService(
            inner,
            cache,
            options,
            NullLogger<CachedMovieSearchService>.Instance);
        return (service, catalog);
    }

    [Fact]
    public async Task An_identical_search_is_served_from_the_cache()
    {
        var (service, catalog) = Build();
        var criteria = MovieSearchCriteria.Create("space horror", 5);

        var first = await service.SearchAsync(criteria, TestContext.Current.CancellationToken);
        var second = await service.SearchAsync(criteria, TestContext.Current.CancellationToken);

        catalog.SearchCallCount.ShouldBe(1);
        first.FromCache.ShouldBeFalse();
        second.FromCache.ShouldBeTrue();
        second.Movies.ShouldBe(first.Movies);
    }

    [Fact]
    public async Task A_search_that_differs_only_in_casing_still_hits_the_cache()
    {
        var (service, catalog) = Build();

        await service.SearchAsync(
            MovieSearchCriteria.Create("Space Horror", 5, "Action"),
            TestContext.Current.CancellationToken);
        var second = await service.SearchAsync(
            MovieSearchCriteria.Create("space horror", 5, "action"),
            TestContext.Current.CancellationToken);

        catalog.SearchCallCount.ShouldBe(1);
        second.FromCache.ShouldBeTrue();
    }

    [Theory]
    [InlineData("different query", 5, null)]
    [InlineData("space horror", 10, null)]
    [InlineData("space horror", 5, "Drama")]
    public async Task A_different_search_misses_the_cache(string query, int topK, string? genre)
    {
        var (service, catalog) = Build();

        await service.SearchAsync(
            MovieSearchCriteria.Create("space horror", 5),
            TestContext.Current.CancellationToken);
        var second = await service.SearchAsync(
            MovieSearchCriteria.Create(query, topK, genre),
            TestContext.Current.CancellationToken);

        catalog.SearchCallCount.ShouldBe(2);
        second.FromCache.ShouldBeFalse();
    }

    [Fact]
    public async Task The_cache_can_be_switched_off()
    {
        var (service, catalog) = Build(enabled: false);
        var criteria = MovieSearchCriteria.Create("space horror");

        await service.SearchAsync(criteria, TestContext.Current.CancellationToken);
        var second = await service.SearchAsync(criteria, TestContext.Current.CancellationToken);

        catalog.SearchCallCount.ShouldBe(2);
        second.FromCache.ShouldBeFalse();
    }

    [Fact]
    public async Task Genres_and_statistics_are_cached()
    {
        var (service, catalog) = Build();

        await service.GetGenresAsync(TestContext.Current.CancellationToken);
        await service.GetGenresAsync(TestContext.Current.CancellationToken);
        await service.GetStatisticsAsync(TestContext.Current.CancellationToken);
        await service.GetStatisticsAsync(TestContext.Current.CancellationToken);

        catalog.GenreCallCount.ShouldBe(1);
        catalog.StatsCallCount.ShouldBe(1);
    }

    [Fact]
    public async Task A_lookup_by_identifier_is_not_cached()
    {
        // It is one indexed read. Caching it would spend memory for no gain, and
        // would delay a correction after the pipeline re-runs.
        var (service, catalog) = Build();

        await service.GetByIdAsync(FakeMovieCatalog.TerminatorId, TestContext.Current.CancellationToken);
        catalog.MovieById = FakeMovieCatalog.Movie(FakeMovieCatalog.TerminatorId, "Renamed", null);
        var second = await service.GetByIdAsync(
            FakeMovieCatalog.TerminatorId,
            TestContext.Current.CancellationToken);

        second!.Title.ShouldBe("Renamed");
    }

    [Fact]
    public async Task A_failing_search_is_not_cached()
    {
        var (service, catalog) = Build();
        catalog.SearchThrows = new InvalidOperationException("catalogue is down");
        var criteria = MovieSearchCriteria.Create("space horror");

        await Should.ThrowAsync<InvalidOperationException>(
            () => service.SearchAsync(criteria, TestContext.Current.CancellationToken));

        catalog.SearchThrows = null;
        var result = await service.SearchAsync(criteria, TestContext.Current.CancellationToken);

        result.FromCache.ShouldBeFalse();
        catalog.SearchCallCount.ShouldBe(2);
    }
}
