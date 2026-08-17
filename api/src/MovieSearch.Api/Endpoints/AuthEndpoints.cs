using Microsoft.AspNetCore.Http.HttpResults;
using Microsoft.AspNetCore.Mvc;
using MovieSearch.Api.Contracts;
using MovieSearch.Application.Auth;

namespace MovieSearch.Api.Endpoints;

/// <summary>The token endpoint.</summary>
internal static class AuthEndpoints
{
    /// <summary>Map the token endpoint.</summary>
    /// <param name="app">Route builder.</param>
    /// <returns>The same route builder.</returns>
    public static IEndpointRouteBuilder MapAuthEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapPost("/auth/token", IssueTokenAsync)
            .AllowAnonymous()
            .WithTags("Authentication")
            .WithName("IssueToken")
            .WithSummary("Exchange client credentials for an access token.")
            .WithDescription(
                "Implements the OAuth 2.0 client-credentials grant. Send the client id and " +
                "secret in a JSON body. The returned token goes in the `Authorization` header " +
                "as `Bearer <token>` on every `/api/v1/*` request.")
            .Produces<TokenResponse>(StatusCodes.Status200OK)
            .ProducesProblem(StatusCodes.Status400BadRequest)
            .ProducesProblem(StatusCodes.Status401Unauthorized);

        return app;
    }

    /// <summary>Exchange client credentials for an access token.</summary>
    /// <param name="request">The client credentials.</param>
    /// <param name="tokens">Token service.</param>
    /// <returns>The token, or 401 when the credentials do not match a configured client.</returns>
    private static Task<Results<Ok<TokenResponse>, BadRequest<ProblemDetails>, UnauthorizedHttpResult>>
        IssueTokenAsync(TokenRequest request, IAccessTokenService tokens)
    {
        if (request is null)
        {
            return Task.FromResult<Results<Ok<TokenResponse>, BadRequest<ProblemDetails>, UnauthorizedHttpResult>>(
                TypedResults.BadRequest(Problem("A request body is required.")));
        }

        if (!request.HasSupportedGrantType())
        {
            return Task.FromResult<Results<Ok<TokenResponse>, BadRequest<ProblemDetails>, UnauthorizedHttpResult>>(
                TypedResults.BadRequest(Problem(
                    $"Unsupported grant_type. Only '{TokenRequest.ClientCredentials}' is accepted.")));
        }

        var token = tokens.Issue(request.ClientId, request.ClientSecret);

        // The same answer for an unknown client and for a wrong secret. Saying
        // which one was wrong would let a caller enumerate valid client ids.
        return Task.FromResult<Results<Ok<TokenResponse>, BadRequest<ProblemDetails>, UnauthorizedHttpResult>>(
            token is null
                ? TypedResults.Unauthorized()
                : TypedResults.Ok(TokenResponse.From(token)));
    }

    private static ProblemDetails Problem(string detail) => new()
    {
        Status = StatusCodes.Status400BadRequest,
        Title = "Invalid token request",
        Detail = detail,
        Type = "https://datatracker.ietf.org/doc/html/rfc9110#section-15.5.1",
    };
}
