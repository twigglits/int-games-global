using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using Microsoft.Extensions.Hosting;
using MovieSearch.Domain.Abstractions;
using MovieSearch.Tests.Fakes;

namespace MovieSearch.Tests.Integration;

/// <summary>
/// Boots the real application with one substitution: the catalogue port.
/// Everything else — authentication, authorization, rate limiting, caching,
/// serialization, the exception handler, the OpenAPI document — is the code that
/// runs in production.
/// </summary>
public sealed class MovieSearchApiFactory : WebApplicationFactory<Program>
{
    public const string SigningKey = "integration-test-signing-key-that-is-long-enough";
    public const string ReaderClientId = "test-reader";
    public const string ReaderSecret = "test-reader-secret-value";
    public const string AdminClientId = "test-admin";
    public const string AdminSecret = "test-admin-secret-value";

    /// <summary>The catalogue the whole application will use.</summary>
    public FakeMovieCatalog Catalog { get; } = new();

    /// <summary>Requests one client may make per window. Lowered per test.</summary>
    public int PermitsPerWindow { get; init; } = 1000;

    /// <summary>Whether the response cache is on.</summary>
    public bool CacheEnabled { get; init; } = true;

    public static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web)
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    };

    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        builder.UseEnvironment(Environments.Development);

        builder.UseSetting("Logging:Directory", Path.Combine(Path.GetTempPath(), "movie-search-tests"));
        builder.UseSetting("Auth:SigningKey", SigningKey);
        builder.UseSetting("Auth:Issuer", "https://test-issuer");
        builder.UseSetting("Auth:Audience", "test-audience");
        builder.UseSetting("Auth:AccessTokenLifetimeMinutes", "60");
        builder.UseSetting("Auth:Clients:0:ClientId", ReaderClientId);
        builder.UseSetting("Auth:Clients:0:ClientSecret", ReaderSecret);
        builder.UseSetting("Auth:Clients:0:Roles:0", "reader");
        builder.UseSetting("Auth:Clients:1:ClientId", AdminClientId);
        builder.UseSetting("Auth:Clients:1:ClientSecret", AdminSecret);
        builder.UseSetting("Auth:Clients:1:Roles:0", "reader");
        builder.UseSetting("Auth:Clients:1:Roles:1", "admin");
        builder.UseSetting("RequestLimits:PermitsPerWindow", PermitsPerWindow.ToString());
        builder.UseSetting("RequestLimits:WindowSeconds", "60");
        builder.UseSetting("Cache:Enabled", CacheEnabled ? "true" : "false");
        builder.UseSetting("Cache:TtlSeconds", "60");
        builder.UseSetting("Mcp:ServerUrl", "http://mcp-server-does-not-exist:8000");

        builder.ConfigureServices(services =>
        {
            services.RemoveAll<IMovieCatalog>();
            services.AddSingleton<IMovieCatalog>(Catalog);
        });
    }

    /// <summary>Obtain a token through the real token endpoint.</summary>
    /// <param name="clientId">Client identifier.</param>
    /// <param name="clientSecret">Client secret.</param>
    /// <returns>An HTTP client that carries the bearer token.</returns>
    public async Task<HttpClient> CreateAuthenticatedClientAsync(string clientId, string clientSecret)
    {
        var client = CreateClient();
        var response = await client.PostAsJsonAsync(
            "/auth/token",
            new { client_id = clientId, client_secret = clientSecret },
            TestContext.Current.CancellationToken);
        response.EnsureSuccessStatusCode();

        var payload = await response.Content.ReadFromJsonAsync<TokenPayload>(
            Json,
            TestContext.Current.CancellationToken);
        client.DefaultRequestHeaders.Authorization =
            new AuthenticationHeaderValue("Bearer", payload!.AccessToken);
        return client;
    }

    /// <summary>Obtain a reader token.</summary>
    /// <returns>An HTTP client with reader rights.</returns>
    public Task<HttpClient> CreateReaderClientAsync() =>
        CreateAuthenticatedClientAsync(ReaderClientId, ReaderSecret);

    /// <summary>Obtain an admin token.</summary>
    /// <returns>An HTTP client with admin rights.</returns>
    public Task<HttpClient> CreateAdminClientAsync() =>
        CreateAuthenticatedClientAsync(AdminClientId, AdminSecret);

    public sealed record TokenPayload(
        string AccessToken,
        string TokenType,
        int ExpiresIn,
        IReadOnlyList<string> Roles);
}
