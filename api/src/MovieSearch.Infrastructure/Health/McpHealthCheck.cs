using System.Text.Json;
using Microsoft.Extensions.Diagnostics.HealthChecks;
using Microsoft.Extensions.Logging;

namespace MovieSearch.Infrastructure.Health;

/// <summary>
/// Readiness check for the MCP server.
/// </summary>
/// <remarks>
/// The check reads the MCP server's own <c>GET /health</c> rather than opening an
/// MCP session. Two reasons:
/// <list type="bullet">
///   <item>The MCP server's health endpoint already reports on the database and
///   the embedding service, so one call covers the whole chain behind this API.</item>
///   <item>A probe that opened an MCP session on every poll would create and
///   destroy sessions on a fixed schedule for no benefit.</item>
/// </list>
/// </remarks>
/// <param name="httpClientFactory">HTTP client factory.</param>
/// <param name="logger">Logger.</param>
public sealed class McpHealthCheck(
    IHttpClientFactory httpClientFactory,
    ILogger<McpHealthCheck> logger) : IHealthCheck
{
    /// <summary>Name of the HTTP client used by this check.</summary>
    public const string HttpClientName = "mcp-health";

    /// <inheritdoc />
    public async Task<HealthCheckResult> CheckHealthAsync(
        HealthCheckContext context,
        CancellationToken cancellationToken = default)
    {
        var client = httpClientFactory.CreateClient(HttpClientName);
        try
        {
            using var response = await client
                .GetAsync(new Uri("health", UriKind.Relative), cancellationToken)
                .ConfigureAwait(false);
            var body = await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
            var data = Describe(body);

            if (response.IsSuccessStatusCode)
            {
                return HealthCheckResult.Healthy("The MCP server is ready.", data);
            }

            return HealthCheckResult.Unhealthy(
                $"The MCP server answered {(int)response.StatusCode}.",
                data: data);
        }
        catch (Exception exception) when (exception is HttpRequestException or TaskCanceledException)
        {
            logger.LogWarning(exception, "The MCP server health endpoint could not be reached.");
            return HealthCheckResult.Unhealthy("The MCP server could not be reached.", exception);
        }
    }

    private static Dictionary<string, object> Describe(string body)
    {
        try
        {
            using var document = JsonDocument.Parse(body);
            var data = new Dictionary<string, object>(StringComparer.Ordinal);
            foreach (var property in document.RootElement.EnumerateObject())
            {
                data[property.Name] = property.Value.ToString();
            }

            return data;
        }
        catch (JsonException)
        {
            return new Dictionary<string, object>(StringComparer.Ordinal)
            {
                ["raw"] = body.Length > 500 ? body[..500] : body,
            };
        }
    }
}
