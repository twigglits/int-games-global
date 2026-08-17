namespace MovieSearch.Application.Auth;

/// <summary>Roles the API recognises.</summary>
public static class Roles
{
    /// <summary>May search and read movies. Cannot read dataset statistics.</summary>
    public const string Reader = "reader";

    /// <summary>May do everything a reader may do, plus read dataset statistics.</summary>
    public const string Admin = "admin";
}

/// <summary>A successful client-credentials exchange.</summary>
/// <param name="Value">The signed JWT.</param>
/// <param name="ExpiresInSeconds">Lifetime of the token in seconds.</param>
/// <param name="Roles">Roles granted to the token.</param>
public sealed record IssuedToken(string Value, int ExpiresInSeconds, IReadOnlyList<string> Roles)
{
    /// <summary>Token type, as required by RFC 6750.</summary>
    public const string TokenType = "Bearer";
}

/// <summary>Issues access tokens for the client-credentials flow.</summary>
public interface IAccessTokenService
{
    /// <summary>Exchange a client id and secret for an access token.</summary>
    /// <param name="clientId">Client identifier.</param>
    /// <param name="clientSecret">Client secret.</param>
    /// <returns>
    /// The token, or null when the credentials do not match a configured client.
    /// The caller must not say which half was wrong.
    /// </returns>
    IssuedToken? Issue(string? clientId, string? clientSecret);
}
