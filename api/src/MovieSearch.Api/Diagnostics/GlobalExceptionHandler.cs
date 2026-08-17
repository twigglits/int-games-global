using System.Diagnostics;
using Microsoft.AspNetCore.Diagnostics;
using Microsoft.AspNetCore.Mvc;
using MovieSearch.Domain.Exceptions;

namespace MovieSearch.Api.Diagnostics;

/// <summary>
/// Turns an exception into an RFC 9457 problem document.
/// </summary>
/// <remarks>
/// One place decides the status code for each failure, so an endpoint never has
/// to repeat the mapping. The rule behind the mapping is who is at fault:
/// <list type="bullet">
///   <item>The caller sent something wrong: 400.</item>
///   <item>The caller asked for something that is not there: 404.</item>
///   <item>A service behind this one failed: 502.</item>
///   <item>A service behind this one was too slow: 504.</item>
///   <item>Anything else: 500, with no internal detail in the body.</item>
/// </list>
/// The trace identifier is always included, so a caller reporting a failure can
/// name the exact trace an operator should open in Jaeger.
/// </remarks>
/// <param name="logger">Logger.</param>
/// <param name="environment">Host environment.</param>
internal sealed class GlobalExceptionHandler(
    ILogger<GlobalExceptionHandler> logger,
    IHostEnvironment environment) : IExceptionHandler
{
    /// <inheritdoc />
    public async ValueTask<bool> TryHandleAsync(
        HttpContext httpContext,
        Exception exception,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(httpContext);
        ArgumentNullException.ThrowIfNull(exception);

        // A cancelled request has no client left to answer.
        if (exception is OperationCanceledException && httpContext.RequestAborted.IsCancellationRequested)
        {
            logger.LogInformation("The client disconnected before {Path} finished.", httpContext.Request.Path);
            return true;
        }

        var problem = Map(exception);
        problem.Instance = httpContext.Request.Path;
        problem.Extensions["traceId"] = Activity.Current?.Id ?? httpContext.TraceIdentifier;

        if (problem.Status >= StatusCodes.Status500InternalServerError)
        {
            logger.LogError(
                exception,
                "Request {Method} {Path} failed with {StatusCode}.",
                httpContext.Request.Method,
                httpContext.Request.Path,
                problem.Status);

            // The exception text may name internal hosts. It is shown only in a
            // development environment.
            if (environment.IsDevelopment())
            {
                problem.Extensions["exception"] = exception.ToString();
            }
        }
        else
        {
            logger.LogInformation(
                "Request {Method} {Path} was rejected with {StatusCode}: {Detail}",
                httpContext.Request.Method,
                httpContext.Request.Path,
                problem.Status,
                problem.Detail);
        }

        Activity.Current?.SetStatus(ActivityStatusCode.Error, exception.Message);

        httpContext.Response.StatusCode = problem.Status ?? StatusCodes.Status500InternalServerError;
        // The content type is passed to the writer rather than set on the
        // response first: WriteAsJsonAsync overwrites whatever is already there.
        await httpContext.Response
            .WriteAsJsonAsync(problem, options: null, contentType: "application/problem+json", cancellationToken)
            .ConfigureAwait(false);
        return true;
    }

    private static ProblemDetails Map(Exception exception) => exception switch
    {
        InvalidSearchCriteriaException invalid => new ProblemDetails
        {
            Status = StatusCodes.Status400BadRequest,
            Title = "Invalid request",
            Detail = invalid.Message,
            Type = "https://datatracker.ietf.org/doc/html/rfc9110#section-15.5.1",
            Extensions = { ["parameter"] = string.IsNullOrEmpty(invalid.ParameterName) ? null : invalid.ParameterName },
        },
        MovieNotFoundException notFound => new ProblemDetails
        {
            Status = StatusCodes.Status404NotFound,
            Title = "Movie not found",
            Detail = notFound.Message,
            Type = "https://datatracker.ietf.org/doc/html/rfc9110#section-15.5.5",
        },
        MovieCatalogUnavailableException unavailable => new ProblemDetails
        {
            Status = StatusCodes.Status502BadGateway,
            Title = "The movie catalogue is unavailable",
            Detail = unavailable.Message,
            Type = "https://datatracker.ietf.org/doc/html/rfc9110#section-15.6.3",
        },
        TimeoutException => new ProblemDetails
        {
            Status = StatusCodes.Status504GatewayTimeout,
            Title = "The request timed out",
            Detail = "The movie catalogue did not answer in time. Try again.",
            Type = "https://datatracker.ietf.org/doc/html/rfc9110#section-15.6.5",
        },
        BadHttpRequestException badRequest => new ProblemDetails
        {
            Status = StatusCodes.Status400BadRequest,
            Title = "Invalid request",
            Detail = badRequest.Message,
            Type = "https://datatracker.ietf.org/doc/html/rfc9110#section-15.5.1",
        },
        _ => new ProblemDetails
        {
            Status = StatusCodes.Status500InternalServerError,
            Title = "Unexpected error",
            Detail = "The request could not be completed. The failure has been logged.",
            Type = "https://datatracker.ietf.org/doc/html/rfc9110#section-15.6.1",
        },
    };
}
