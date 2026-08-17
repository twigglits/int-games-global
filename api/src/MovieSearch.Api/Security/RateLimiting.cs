using System.Globalization;
using System.Security.Claims;
using System.Threading.RateLimiting;
using Microsoft.AspNetCore.RateLimiting;
using Microsoft.Extensions.Options;
using MovieSearch.Infrastructure.Configuration;

namespace MovieSearch.Api.Security;

/// <summary>Names of the rate limiting policies.</summary>
internal static class RateLimitPolicies
{
    /// <summary>One budget per authenticated client.</summary>
    public const string PerClient = "per-client";
}

/// <summary>Rate limiting configuration.</summary>
internal static class RateLimitingSetup
{
    /// <summary>Add the per-client rate limiter.</summary>
    /// <param name="services">Service collection.</param>
    /// <returns>The same service collection.</returns>
    /// <remarks>
    /// The budget is partitioned by the token's subject, so one noisy client
    /// cannot spend another client's allowance. An unauthenticated request falls
    /// back to its remote address, which only matters for a request that reaches
    /// the limiter before authentication fails.
    ///
    /// A fixed window, not a sliding one: the requirement is stated as a count
    /// per minute, and a fixed window is the cheapest structure that expresses
    /// exactly that. It admits a burst across a window boundary; the alternative
    /// costs memory per partition for a limit that is generous either way.
    /// </remarks>
    public static IServiceCollection AddMovieSearchRateLimiting(this IServiceCollection services)
    {
        services.AddRateLimiter(limiterOptions =>
        {
            limiterOptions.RejectionStatusCode = StatusCodes.Status429TooManyRequests;

            limiterOptions.AddPolicy(RateLimitPolicies.PerClient, httpContext =>
            {
                var limits = httpContext.RequestServices
                    .GetRequiredService<IOptions<RequestLimitOptions>>().Value;

                var partitionKey = httpContext.User.FindFirstValue(ClaimTypes.NameIdentifier)
                    ?? httpContext.User.FindFirstValue("sub")
                    ?? httpContext.User.FindFirstValue("client_id")
                    ?? httpContext.Connection.RemoteIpAddress?.ToString()
                    ?? "anonymous";

                return RateLimitPartition.GetFixedWindowLimiter(
                    partitionKey,
                    _ => new FixedWindowRateLimiterOptions
                    {
                        PermitLimit = limits.PermitsPerWindow,
                        Window = TimeSpan.FromSeconds(limits.WindowSeconds),
                        QueueLimit = limits.QueueLimit,
                        QueueProcessingOrder = QueueProcessingOrder.OldestFirst,
                        AutoReplenishment = true,
                    });
            });

            // A rejected caller is told when to come back, so a well-behaved
            // client can wait rather than retry immediately and make it worse.
            limiterOptions.OnRejected = static async (context, cancellationToken) =>
            {
                if (context.Lease.TryGetMetadata(MetadataName.RetryAfter, out var retryAfter))
                {
                    context.HttpContext.Response.Headers.RetryAfter =
                        ((int)retryAfter.TotalSeconds).ToString(CultureInfo.InvariantCulture);
                }

                context.HttpContext.Response.StatusCode = StatusCodes.Status429TooManyRequests;
                context.HttpContext.Response.ContentType = "application/problem+json";
                await context.HttpContext.Response.WriteAsync(
                    """
                    {"type":"https://datatracker.ietf.org/doc/html/rfc6585#section-4",
                     "title":"Too many requests",
                     "status":429,
                     "detail":"The request rate for this client has been exceeded. Retry after the number of seconds in the Retry-After header."}
                    """,
                    cancellationToken).ConfigureAwait(false);
            };
        });

        return services;
    }
}
