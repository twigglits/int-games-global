using System.Text.Json;
using System.Text.Json.Serialization;
using MovieSearch.Api.Diagnostics;
using MovieSearch.Api.Endpoints;
using MovieSearch.Api.Observability;
using MovieSearch.Api.OpenApi;
using MovieSearch.Api.Security;
using MovieSearch.Infrastructure;
using OpenTelemetry.Metrics;
using Serilog;

// ---------------------------------------------------------------------------
// Why Minimal APIs and not controllers.
//
// The surface is six read endpoints and one token endpoint. Minimal APIs give
// three things that matter here:
//
//  * Typed results. `Results<Ok<T>, NotFound<ProblemDetails>>` states every
//    outcome in the signature, and the OpenAPI document is generated from that
//    signature rather than from attributes that can disagree with the code.
//  * Route groups. Authorization and rate limiting are declared once per group,
//    so a new endpoint cannot be added without them by forgetting a line.
//  * No per-request controller activation, model binder pipeline or filter
//    pipeline, which is measurable on a p95 budget of 500 ms.
//
// Controllers earn their place on a large surface with heavy conventions,
// shared model binders and inherited filters. This is not that.
// ---------------------------------------------------------------------------

var builder = WebApplication.CreateBuilder(args);

builder.AddMovieSearchLogging();
builder.AddMovieSearchTelemetry();

// The whole public API uses snake_case, because the query parameters are
// snake_case. One convention across parameters and bodies beats two.
builder.Services.ConfigureHttpJsonOptions(options =>
{
    options.SerializerOptions.PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower;
    options.SerializerOptions.DictionaryKeyPolicy = JsonNamingPolicy.SnakeCaseLower;
    options.SerializerOptions.DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull;
    options.SerializerOptions.Converters.Add(new JsonStringEnumConverter());
});

builder.Services.AddMovieSearchInfrastructure(builder.Configuration);
builder.Services.AddMovieSearchAuthentication();
builder.Services.AddMovieSearchRateLimiting();
builder.Services.AddMovieSearchOpenApi();

builder.Services.AddProblemDetails();
builder.Services.AddExceptionHandler<GlobalExceptionHandler>();

// A request that outlives its budget is abandoned rather than left to hold a
// connection. The value comes from configuration; 30 seconds is the default.
builder.Services.AddRequestTimeouts(options =>
{
    var seconds = builder.Configuration.GetValue("RequestLimits:RequestTimeoutSeconds", 30);
    options.DefaultPolicy = new Microsoft.AspNetCore.Http.Timeouts.RequestTimeoutPolicy
    {
        Timeout = TimeSpan.FromSeconds(seconds),
        TimeoutStatusCode = StatusCodes.Status504GatewayTimeout,
    };
});

var app = builder.Build();

app.UseExceptionHandler();
app.UseSerilogRequestLogging(options =>
{
    options.MessageTemplate =
        "{RequestMethod} {RequestPath} answered {StatusCode} in {Elapsed:0.0000} ms";
    options.GetLevel = static (httpContext, _, exception) =>
        exception is not null || httpContext.Response.StatusCode >= 500
            ? Serilog.Events.LogEventLevel.Error
            : httpContext.Request.Path.StartsWithSegments("/health")
              || httpContext.Request.Path.StartsWithSegments("/metrics")
                ? Serilog.Events.LogEventLevel.Verbose
                : Serilog.Events.LogEventLevel.Information;
    options.EnrichDiagnosticContext = static (diagnostic, httpContext) =>
    {
        diagnostic.Set("ClientId", httpContext.User.FindFirst("client_id")?.Value);
        diagnostic.Set("RequestQuery", httpContext.Request.QueryString.Value);
    };
});

app.UseRequestTimeouts();
app.UseAuthentication();
app.UseAuthorization();

// The rate limiter runs after authentication on purpose: it partitions the
// budget by the token's subject, and before authentication there is no subject
// to partition by, so every client would share one bucket.
app.UseRateLimiter();

// The document at /openapi/v1.json, and the Swagger UI that renders it.
app.MapOpenApi("/openapi/{documentName}.json").AllowAnonymous();
app.UseSwaggerUI(options =>
{
    options.SwaggerEndpoint($"/openapi/{OpenApiSetup.DocumentName}.json", "Movie Search API v1");
    options.RoutePrefix = "swagger";
    options.DocumentTitle = "Intelligent Movie Search API";
    options.DisplayRequestDuration();
});

// Prometheus scrapes this. It is intentionally anonymous: the endpoint is bound
// inside the container network, and a scrape that needed a token would need the
// token to be distributed to Prometheus.
app.MapPrometheusScrapingEndpoint("/metrics").AllowAnonymous();

app.MapHealthEndpoints();
app.MapAuthEndpoints();
app.MapMovieEndpoints();

// A convenience for a person who opens the root URL.
app.MapGet("/", () => Results.Redirect("/swagger"))
    .AllowAnonymous()
    .ExcludeFromDescription();

try
{
    Log.Information("Movie Search API starting in the {Environment} environment", app.Environment.EnvironmentName);
    await app.RunAsync().ConfigureAwait(false);
}
catch (Exception exception)
{
    Log.Fatal(exception, "The Movie Search API stopped because of an unhandled exception");
    throw;
}
finally
{
    await Log.CloseAndFlushAsync().ConfigureAwait(false);
}

/// <summary>
/// Exposed so that the integration tests can build the same application through
/// <c>WebApplicationFactory</c>. A test that started a different application
/// would prove nothing about this one.
/// </summary>
public partial class Program;
