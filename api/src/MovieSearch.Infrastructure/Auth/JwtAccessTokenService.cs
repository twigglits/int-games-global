using System.Globalization;
using System.Security.Claims;
using System.Security.Cryptography;
using System.Text;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Microsoft.IdentityModel.JsonWebTokens;
using Microsoft.IdentityModel.Tokens;
using MovieSearch.Application.Auth;
using MovieSearch.Infrastructure.Configuration;

namespace MovieSearch.Infrastructure.Auth;

/// <summary>
/// Issues signed JWTs for the client-credentials flow.
/// </summary>
/// <remarks>
/// Two things here are deliberate and are not shortcuts:
/// <list type="bullet">
///   <item>The secret comparison is constant time. A plain string comparison
///   returns as soon as two bytes differ, which leaks the length of the matching
///   prefix to anyone who can measure the response time.</item>
///   <item>A wrong client id and a wrong secret produce the same answer. Telling
///   the caller which half was wrong turns the endpoint into a client-id
///   oracle.</item>
/// </list>
/// The signing key is symmetric. That is correct for a single service that both
/// issues and validates its own tokens. A second service that needed to validate
/// these tokens without being able to mint them would want an asymmetric key and
/// a published JWKS, and that is noted as a limitation in the README.
/// </remarks>
/// <param name="options">Auth settings.</param>
/// <param name="logger">Logger.</param>
public sealed class JwtAccessTokenService(
    IOptions<AuthOptions> options,
    ILogger<JwtAccessTokenService> logger) : IAccessTokenService
{
    private readonly AuthOptions _options = options.Value;
    private readonly JsonWebTokenHandler _handler = new();

    /// <inheritdoc />
    public IssuedToken? Issue(string? clientId, string? clientSecret)
    {
        if (string.IsNullOrWhiteSpace(clientId) || string.IsNullOrWhiteSpace(clientSecret))
        {
            return null;
        }

        var client = _options.Clients.FirstOrDefault(
            candidate => string.Equals(candidate.ClientId, clientId, StringComparison.Ordinal));

        // Run the comparison even when the client id is unknown, against a
        // dummy secret of the same shape. That keeps the timing of an unknown
        // client and a wrong secret the same.
        var expected = client?.ClientSecret ?? string.Empty;
        var secretMatches = FixedTimeEquals(expected, clientSecret);

        if (client is null || !secretMatches)
        {
            logger.LogWarning(
                "Rejected a token request for client {ClientId}.",
                Sanitise(clientId));
            return null;
        }

        var lifetime = TimeSpan.FromMinutes(_options.AccessTokenLifetimeMinutes);
        var now = DateTime.UtcNow;
        var roles = client.Roles.Count > 0 ? client.Roles.ToList() : [Roles.Reader];

        var claims = new List<Claim>
        {
            new(JwtRegisteredClaimNames.Sub, client.ClientId),
            new(JwtRegisteredClaimNames.Jti, Guid.NewGuid().ToString()),
            new("client_id", client.ClientId),
        };
        claims.AddRange(roles.Select(role => new Claim(ClaimTypes.Role, role)));

        var descriptor = new SecurityTokenDescriptor
        {
            Issuer = _options.Issuer,
            Audience = _options.Audience,
            Subject = new ClaimsIdentity(claims),
            IssuedAt = now,
            NotBefore = now,
            Expires = now.Add(lifetime),
            SigningCredentials = new SigningCredentials(
                new SymmetricSecurityKey(Encoding.UTF8.GetBytes(_options.SigningKey)),
                SecurityAlgorithms.HmacSha256),
        };

        var token = _handler.CreateToken(descriptor);
        logger.LogInformation(
            "Issued a token for client {ClientId} with roles {Roles}, valid for {Minutes} minutes.",
            client.ClientId,
            string.Join(',', roles),
            _options.AccessTokenLifetimeMinutes);

        return new IssuedToken(
            token,
            (int)lifetime.TotalSeconds,
            roles);
    }

    private static bool FixedTimeEquals(string expected, string supplied)
    {
        var expectedBytes = Encoding.UTF8.GetBytes(expected);
        var suppliedBytes = Encoding.UTF8.GetBytes(supplied);

        // FixedTimeEquals needs equal lengths, and the length itself must not
        // decide the running time. Both sides are hashed first, which makes the
        // compared buffers the same size whatever the inputs were.
        Span<byte> expectedHash = stackalloc byte[32];
        Span<byte> suppliedHash = stackalloc byte[32];
        SHA256.HashData(expectedBytes, expectedHash);
        SHA256.HashData(suppliedBytes, suppliedHash);
        return CryptographicOperations.FixedTimeEquals(expectedHash, suppliedHash)
            && expected.Length > 0;
    }

    private static string Sanitise(string value)
    {
        // A client id reaches the log. Newlines are removed so that a crafted id
        // cannot forge extra log lines, and the value is capped.
        var cleaned = value.Replace('\n', ' ').Replace('\r', ' ');
        return cleaned.Length <= 64
            ? cleaned
            : string.Concat(cleaned.AsSpan(0, 64), "...".AsSpan()).ToString(CultureInfo.InvariantCulture);
    }
}
