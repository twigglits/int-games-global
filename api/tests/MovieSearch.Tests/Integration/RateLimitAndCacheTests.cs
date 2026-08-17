using System.Net;
using System.Text.Json;

namespace MovieSearch.Tests.Integration;

/// <summary>
/// Rate limiting and response caching both need their own application instance,
/// because a shared one would carry state between tests.
/// </summary>
public class RateLimitAndCacheTests
{
    private static CancellationToken Token => TestContext.Current.CancellationToken;

    [Fact]
    public async Task A_client_over_its_budget_is_answered_with_429_and_a_retry_after_header()
    {
        await using var factory = new MovieSearchApiFactory { PermitsPerWindow = 3 };
        var client = await factory.CreateReaderClientAsync();

        var statuses = new List<HttpStatusCode>();
        HttpResponseMessage? rejected = null;
        for (var request = 0; request < 5; request++)
        {
            var response = await client.GetAsync($"/api/v1/movies/search?q=query{request}", Token);
            statuses.Add(response.StatusCode);
            if (response.StatusCode == HttpStatusCode.TooManyRequests)
            {
                rejected ??= response;
            }
        }

        statuses.Count(status => status == HttpStatusCode.OK).ShouldBe(3);
        statuses.Count(status => status == HttpStatusCode.TooManyRequests).ShouldBe(2);
        rejected.ShouldNotBeNull();
        rejected.Headers.RetryAfter.ShouldNotBeNull();
        (await rejected.Content.ReadAsStringAsync(Token)).ShouldContain("Too many requests");
    }

    [Fact]
    public async Task One_client_over_its_budget_does_not_block_another_client()
    {
        await using var factory = new MovieSearchApiFactory { PermitsPerWindow = 2 };
        var reader = await factory.CreateReaderClientAsync();
        var admin = await factory.CreateAdminClientAsync();

        for (var request = 0; request < 3; request++)
        {
            await reader.GetAsync($"/api/v1/movies/search?q=q{request}", Token);
        }

        var readerResponse = await reader.GetAsync("/api/v1/movies/search?q=blocked", Token);
        var adminResponse = await admin.GetAsync("/api/v1/movies/search?q=allowed", Token);

        readerResponse.StatusCode.ShouldBe(HttpStatusCode.TooManyRequests);
        adminResponse.StatusCode.ShouldBe(HttpStatusCode.OK);
    }

    [Fact]
    public async Task An_identical_search_is_answered_from_the_cache()
    {
        await using var factory = new MovieSearchApiFactory { CacheEnabled = true };
        var client = await factory.CreateReaderClientAsync();

        await client.GetAsync("/api/v1/movies/search?q=repeated", Token);
        var response = await client.GetAsync("/api/v1/movies/search?q=repeated", Token);

        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync(Token));
        document.RootElement.GetProperty("cached").GetBoolean().ShouldBeTrue();
        factory.Catalog.SearchCallCount.ShouldBe(1);
    }

    [Fact]
    public async Task The_cache_can_be_switched_off_by_configuration()
    {
        await using var factory = new MovieSearchApiFactory { CacheEnabled = false };
        var client = await factory.CreateReaderClientAsync();

        await client.GetAsync("/api/v1/movies/search?q=repeated", Token);
        var response = await client.GetAsync("/api/v1/movies/search?q=repeated", Token);

        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync(Token));
        document.RootElement.GetProperty("cached").GetBoolean().ShouldBeFalse();
        factory.Catalog.SearchCallCount.ShouldBe(2);
    }

    [Fact]
    public async Task The_cache_key_ignores_the_order_of_the_query_parameters()
    {
        await using var factory = new MovieSearchApiFactory { CacheEnabled = true };
        var client = await factory.CreateReaderClientAsync();

        await client.GetAsync("/api/v1/movies/search?q=order&top_k=5&genre=Action", Token);
        var response = await client.GetAsync("/api/v1/movies/search?genre=Action&q=order&top_k=5", Token);

        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync(Token));
        document.RootElement.GetProperty("cached").GetBoolean().ShouldBeTrue();
        factory.Catalog.SearchCallCount.ShouldBe(1);
    }
}
