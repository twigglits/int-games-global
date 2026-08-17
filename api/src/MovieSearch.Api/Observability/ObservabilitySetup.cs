using MovieSearch.Infrastructure.Mcp;
using OpenTelemetry.Metrics;
using OpenTelemetry.Resources;
using OpenTelemetry.Trace;
using Serilog;
using Serilog.Events;
using Serilog.Formatting.Compact;

namespace MovieSearch.Api.Observability;

/// <summary>Tracing, metrics and structured logging.</summary>
internal static class ObservabilitySetup
{
    /// <summary>Name of the service as it appears in traces and metrics.</summary>
    public const string ServiceName = "movie-search-api";

    /// <summary>Add Serilog with a JSON console sink and a rolling file sink.</summary>
    /// <param name="builder">Host application builder.</param>
    /// <returns>The same builder.</returns>
    /// <remarks>
    /// Both sinks receive the same compact JSON. A container log collector reads
    /// stdout; the file exists because the specification asks for one, and
    /// because it survives a crash that stdout buffering could lose.
    /// </remarks>
    public static WebApplicationBuilder AddMovieSearchLogging(this WebApplicationBuilder builder)
    {
        var logDirectory = builder.Configuration["Logging:Directory"] ?? "/app/logs";
        Directory.CreateDirectory(logDirectory);

        builder.Host.UseSerilog((context, services, configuration) => configuration
            .ReadFrom.Configuration(context.Configuration)
            .ReadFrom.Services(services)
            .Enrich.FromLogContext()
            .Enrich.WithEnvironmentName()
            .Enrich.WithProperty("service.name", ServiceName)
            .MinimumLevel.Information()
            .MinimumLevel.Override("Microsoft.AspNetCore", LogEventLevel.Warning)
            .MinimumLevel.Override("Microsoft.Hosting.Lifetime", LogEventLevel.Information)
            .MinimumLevel.Override("System.Net.Http.HttpClient", LogEventLevel.Warning)
            .WriteTo.Console(new CompactJsonFormatter())
            .WriteTo.File(
                new CompactJsonFormatter(),
                Path.Combine(logDirectory, "movie-search-api-.json"),
                rollingInterval: RollingInterval.Day,
                retainedFileCountLimit: 7,
                shared: true));

        return builder;
    }

    /// <summary>Add OpenTelemetry tracing and metrics.</summary>
    /// <param name="builder">Host application builder.</param>
    /// <returns>The same builder.</returns>
    /// <remarks>
    /// Traces go to an OTLP endpoint, which is Jaeger locally and the AWS Distro
    /// for OpenTelemetry sidecar in production. Metrics are exposed for
    /// Prometheus to scrape at <c>/metrics</c> rather than pushed, so a stopped
    /// scrape shows as a gap instead of silently losing data.
    ///
    /// HTTP client instrumentation is what carries the trace to the Python MCP
    /// server: it writes the W3C <c>traceparent</c> header onto every outgoing
    /// request, and the MCP server reads it back off, so one Jaeger trace covers
    /// both services.
    /// </remarks>
    public static WebApplicationBuilder AddMovieSearchTelemetry(this WebApplicationBuilder builder)
    {
        var otlpEndpoint = builder.Configuration["OTEL_EXPORTER_OTLP_ENDPOINT"];
        var serviceVersion = typeof(ObservabilitySetup).Assembly.GetName().Version?.ToString() ?? "1.0.0";

        builder.Services.AddOpenTelemetry()
            .ConfigureResource(resource => resource.AddService(ServiceName, serviceVersion: serviceVersion))
            .WithTracing(tracing =>
            {
                tracing
                    .AddAspNetCoreInstrumentation(options =>
                    {
                        // The health and metrics routes are polled several times
                        // a minute for ever. Tracing them would bury the traces
                        // that matter.
                        options.Filter = static context =>
                            !context.Request.Path.StartsWithSegments("/health")
                            && !context.Request.Path.StartsWithSegments("/metrics");
                        options.RecordException = true;
                    })
                    .AddHttpClientInstrumentation(options => options.RecordException = true)
                    .AddSource(McpMovieCatalog.ActivitySourceName);

                if (!string.IsNullOrWhiteSpace(otlpEndpoint))
                {
                    tracing.AddOtlpExporter();
                }
            })
            .WithMetrics(metrics => metrics
                .AddAspNetCoreInstrumentation()
                .AddHttpClientInstrumentation()
                .AddRuntimeInstrumentation()
                .AddMeter("MovieSearch.Mcp")
                .AddMeter("MovieSearch.Cache")
                .AddMeter("Microsoft.AspNetCore.Hosting")
                .AddMeter("Microsoft.AspNetCore.Server.Kestrel")
                .AddMeter("Microsoft.AspNetCore.RateLimiting")
                .AddView(
                    "http.server.request.duration",
                    new ExplicitBucketHistogramConfiguration
                    {
                        // Buckets chosen around the 500 ms target at p95, so the
                        // quantile can be read off the histogram with useful
                        // resolution where it matters.
                        Boundaries = [0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1, 2.5, 5, 10],
                    })
                .AddPrometheusExporter());

        return builder;
    }
}
