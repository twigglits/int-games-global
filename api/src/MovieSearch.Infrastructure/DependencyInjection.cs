using Microsoft.Extensions.Caching.Memory;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using Microsoft.Extensions.Diagnostics.HealthChecks;
using Microsoft.Extensions.Options;
using MovieSearch.Application.Auth;
using MovieSearch.Application.Movies;
using MovieSearch.Domain.Abstractions;
using MovieSearch.Infrastructure.Auth;
using MovieSearch.Infrastructure.Caching;
using MovieSearch.Infrastructure.Configuration;
using MovieSearch.Infrastructure.Health;
using MovieSearch.Infrastructure.Mcp;

namespace MovieSearch.Infrastructure;

/// <summary>Registers everything the infrastructure layer provides.</summary>
public static class DependencyInjection
{
    /// <summary>Add the MCP catalogue, the response cache and the token service.</summary>
    /// <param name="services">Service collection.</param>
    /// <param name="configuration">Application configuration.</param>
    /// <returns>The same service collection.</returns>
    public static IServiceCollection AddMovieSearchInfrastructure(
        this IServiceCollection services,
        IConfiguration configuration)
    {
        ArgumentNullException.ThrowIfNull(services);
        ArgumentNullException.ThrowIfNull(configuration);

        // Options are validated at startup, not on first use. A missing signing
        // key must stop the process, not surface as a 500 on the first request.
        services.AddOptions<McpOptions>()
            .Bind(configuration.GetSection(McpOptions.SectionName))
            .ValidateDataAnnotations()
            .ValidateOnStart();

        services.AddOptions<CacheOptions>()
            .Bind(configuration.GetSection(CacheOptions.SectionName))
            .ValidateDataAnnotations()
            .ValidateOnStart();

        services.AddOptions<RequestLimitOptions>()
            .Bind(configuration.GetSection(RequestLimitOptions.SectionName))
            .ValidateDataAnnotations()
            .ValidateOnStart();

        services.AddOptions<AuthOptions>()
            .Bind(configuration.GetSection(AuthOptions.SectionName))
            .ValidateDataAnnotations()
            .Validate(
                options => options.Clients.Count > 0,
                "Auth:Clients must contain at least one client, otherwise no token can ever be issued.")
            .Validate(
                options => options.Clients.All(client => client.ClientSecret.Length >= 16),
                "Every Auth:Clients secret must be at least 16 characters long.")
            .ValidateOnStart();

        // The MCP transport's HTTP client. Registering it through the factory is
        // what lets the tracing instrumentation add the traceparent header.
        services.AddHttpClient(McpSessionProvider.HttpClientName)
            .ConfigureHttpClient(static (provider, client) =>
            {
                var options = provider.GetRequiredService<IOptions<McpOptions>>().Value;
                // The MCP session uses a long-lived stream, so the client itself
                // must not impose a timeout. Each call has its own token.
                client.Timeout = Timeout.InfiniteTimeSpan;
                client.DefaultRequestHeaders.UserAgent.ParseAdd("MovieSearch.Api/1.0");
                client.BaseAddress = new Uri(options.ServerUrl.TrimEnd('/') + "/");
            });

        // A separate short-lived client for the MCP server's own health endpoint.
        services.AddHttpClient(McpHealthCheck.HttpClientName)
            .ConfigureHttpClient(static (provider, client) =>
            {
                var options = provider.GetRequiredService<IOptions<McpOptions>>().Value;
                client.BaseAddress = new Uri(options.ServerUrl.TrimEnd('/') + "/");
                client.Timeout = TimeSpan.FromSeconds(5);
            });

        services.TryAddSingleton<IMcpSessionProvider, McpSessionProvider>();
        services.TryAddSingleton<IMovieCatalog, McpMovieCatalog>();
        services.TryAddSingleton<IAccessTokenService, JwtAccessTokenService>();

        services.AddMemoryCache();
        services.AddOptions<MemoryCacheOptions>()
            .Configure<IOptions<CacheOptions>>(static (memoryOptions, cacheOptions) =>
                memoryOptions.SizeLimit = cacheOptions.Value.SizeLimit);

        // The concrete service first, then the cache decorator in front of it.
        services.AddSingleton<MovieSearchService>();
        services.AddSingleton<IMovieSearchService>(provider => new CachedMovieSearchService(
            provider.GetRequiredService<MovieSearchService>(),
            provider.GetRequiredService<IMemoryCache>(),
            provider.GetRequiredService<IOptions<CacheOptions>>(),
            provider.GetRequiredService<Microsoft.Extensions.Logging.ILogger<CachedMovieSearchService>>()));

        services.AddHealthChecks()
            .AddCheck<McpHealthCheck>(
                "mcp-server",
                HealthStatus.Unhealthy,
                tags: ["ready", "dependency"]);

        return services;
    }
}
