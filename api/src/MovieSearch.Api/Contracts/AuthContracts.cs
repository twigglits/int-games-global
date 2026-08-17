using System.ComponentModel.DataAnnotations;
using MovieSearch.Application.Auth;

namespace MovieSearch.Api.Contracts;

/// <summary>A client-credentials token request.</summary>
/// <param name="ClientId">Client identifier.</param>
/// <param name="ClientSecret">Client secret.</param>
/// <param name="GrantType">
/// OAuth 2.0 grant type. Only <c>client_credentials</c> is supported. The field
/// may be omitted, in which case <c>client_credentials</c> is assumed.
/// </param>
public sealed record TokenRequest(
    [property: Required] string ClientId,
    [property: Required] string ClientSecret,
    string? GrantType = null)
{
    /// <summary>The only grant type this API supports.</summary>
    public const string ClientCredentials = "client_credentials";

    /// <summary>Whether the requested grant type is supported.</summary>
    /// <returns>True when the grant type is absent or is the client-credentials grant.</returns>
    public bool HasSupportedGrantType() =>
        string.IsNullOrWhiteSpace(GrantType)
        || string.Equals(GrantType, ClientCredentials, StringComparison.Ordinal);
}

/// <summary>A successfully issued access token.</summary>
/// <param name="AccessToken">The signed JWT. Send it as <c>Authorization: Bearer &lt;token&gt;</c>.</param>
/// <param name="TokenType">Always <c>Bearer</c>.</param>
/// <param name="ExpiresIn">Lifetime of the token in seconds.</param>
/// <param name="Roles">Roles the token grants.</param>
public sealed record TokenResponse(
    string AccessToken,
    string TokenType,
    int ExpiresIn,
    IReadOnlyList<string> Roles)
{
    /// <summary>Build a response from an issued token.</summary>
    /// <param name="token">The issued token.</param>
    /// <returns>The response shape.</returns>
    public static TokenResponse From(IssuedToken token)
    {
        ArgumentNullException.ThrowIfNull(token);
        return new TokenResponse(token.Value, IssuedToken.TokenType, token.ExpiresInSeconds, token.Roles);
    }
}
