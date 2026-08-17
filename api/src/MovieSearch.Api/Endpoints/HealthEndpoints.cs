using System.Text.Json;
using Microsoft.AspNetCore.Diagnostics.HealthChecks;
using Microsoft.Extensions.Diagnostics.HealthChecks;

namespace MovieSearch.Api.Endpoints;

/// <summary>The health endpoints.</summary>
/// <remarks>
/// Three routes, because a container orchestrator asks two different questions:
/// <list type="bullet">
///   <item><c>/health/live</c> — is the process alive? It runs no dependency
///   check at all. A liveness probe that fails when a downstream service is down
///   makes the orchestrator restart a healthy container and lose the recovery it
///   would otherwise have made.</item>
///   <item><c>/health/ready</c> — can this instance serve traffic? It checks the
///   MCP server, and through it the database and the embedding service.</item>
///   <item><c>/health</c> — everything, with the detail. This is the route a
///   person opens.</item>
/// </list>
/// </remarks>
internal static class HealthEndpoints
{
    /// <summary>Tag on checks that must pass before traffic is accepted.</summary>
    public const string ReadyTag = "ready";

    /// <summary>Map the health endpoints.</summary>
    /// <param name="app">Route builder.</param>
    /// <returns>The same route builder.</returns>
    public static IEndpointRouteBuilder MapHealthEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapHealthChecks("/health", new HealthCheckOptions { ResponseWriter = WriteResponseAsync })
            .AllowAnonymous()
            .WithTags("Operations")
            .WithName("Health")
            .WithSummary("Liveness and readiness in one answer.")
            .ExcludeFromDescription();

        app.MapHealthChecks(
                "/health/live",
                new HealthCheckOptions
                {
                    // No dependency check: this answers "is the process alive".
                    Predicate = static _ => false,
                    ResponseWriter = WriteResponseAsync,
                })
            .AllowAnonymous()
            .ExcludeFromDescription();

        app.MapHealthChecks(
                "/health/ready",
                new HealthCheckOptions
                {
                    Predicate = static registration => registration.Tags.Contains(ReadyTag),
                    ResponseWriter = WriteResponseAsync,
                })
            .AllowAnonymous()
            .ExcludeFromDescription();

        return app;
    }

    private static async Task WriteResponseAsync(HttpContext context, HealthReport report)
    {
        context.Response.ContentType = "application/json; charset=utf-8";

        var payload = new
        {
            status = report.Status.ToString().ToLowerInvariant(),
            total_duration_ms = Math.Round(report.TotalDuration.TotalMilliseconds, 2),
            checks = report.Entries.Select(entry => new
            {
                name = entry.Key,
                status = entry.Value.Status.ToString().ToLowerInvariant(),
                description = entry.Value.Description,
                duration_ms = Math.Round(entry.Value.Duration.TotalMilliseconds, 2),
                error = entry.Value.Exception?.Message,
                data = entry.Value.Data.Count == 0 ? null : entry.Value.Data,
            }).ToList(),
        };

        await context.Response
            .WriteAsync(JsonSerializer.Serialize(payload, HealthJson.Options), context.RequestAborted)
            .ConfigureAwait(false);
    }

    private static class HealthJson
    {
        public static readonly JsonSerializerOptions Options = new()
        {
            WriteIndented = false,
            DefaultIgnoreCondition = System.Text.Json.Serialization.JsonIgnoreCondition.WhenWritingNull,
        };
    }
}
