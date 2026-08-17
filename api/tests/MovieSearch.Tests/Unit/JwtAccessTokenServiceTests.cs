using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using System.Text;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Microsoft.IdentityModel.Tokens;
using MovieSearch.Application.Auth;
using MovieSearch.Infrastructure.Auth;
using MovieSearch.Infrastructure.Configuration;

namespace MovieSearch.Tests.Unit;

public class JwtAccessTokenServiceTests
{
    private const string SigningKey = "a-test-signing-key-that-is-long-enough-for-hmac-sha256";

    private static readonly AuthOptions Options = new()
    {
        Issuer = "https://test-issuer",
        Audience = "test-audience",
        SigningKey = SigningKey,
        AccessTokenLifetimeMinutes = 30,
        Clients =
        {
            new ClientCredentialOptions
            {
                ClientId = "reader-client",
                ClientSecret = "reader-secret-value",
                Roles = { Roles.Reader },
            },
            new ClientCredentialOptions
            {
                ClientId = "admin-client",
                ClientSecret = "admin-secret-value",
                Roles = { Roles.Reader, Roles.Admin },
            },
            new ClientCredentialOptions
            {
                ClientId = "roleless-client",
                ClientSecret = "roleless-secret-value",
            },
        },
    };

    private static JwtAccessTokenService CreateService() =>
        new(Microsoft.Extensions.Options.Options.Create(Options), NullLogger<JwtAccessTokenService>.Instance);

    [Fact]
    public void Issue_returns_a_token_for_valid_credentials()
    {
        var token = CreateService().Issue("reader-client", "reader-secret-value");

        token.ShouldNotBeNull();
        token.Value.ShouldNotBeNullOrWhiteSpace();
        token.ExpiresInSeconds.ShouldBe(30 * 60);
        IssuedToken.TokenType.ShouldBe("Bearer");
    }

    [Fact]
    public void The_token_carries_the_configured_roles()
    {
        var token = CreateService().Issue("admin-client", "admin-secret-value");

        token.ShouldNotBeNull();
        token.Roles.ShouldBe([Roles.Reader, Roles.Admin]);
    }

    [Fact]
    public void A_client_with_no_configured_role_gets_reader()
    {
        var token = CreateService().Issue("roleless-client", "roleless-secret-value");

        token.ShouldNotBeNull();
        token.Roles.ShouldBe([Roles.Reader]);
    }

    [Fact]
    public void The_token_validates_against_the_configured_issuer_audience_and_key()
    {
        var token = CreateService().Issue("admin-client", "admin-secret-value");
        token.ShouldNotBeNull();

        var parameters = new TokenValidationParameters
        {
            ValidateIssuer = true,
            ValidIssuer = Options.Issuer,
            ValidateAudience = true,
            ValidAudience = Options.Audience,
            ValidateIssuerSigningKey = true,
            IssuerSigningKey = new SymmetricSecurityKey(Encoding.UTF8.GetBytes(SigningKey)),
            ValidateLifetime = true,
            RoleClaimType = ClaimTypes.Role,
        };

        var principal = new JwtSecurityTokenHandler().ValidateToken(token.Value, parameters, out _);

        principal.FindFirst("client_id")!.Value.ShouldBe("admin-client");
        principal.IsInRole(Roles.Admin).ShouldBeTrue();
        principal.IsInRole(Roles.Reader).ShouldBeTrue();
    }

    [Fact]
    public void A_token_signed_with_another_key_does_not_validate()
    {
        var token = CreateService().Issue("reader-client", "reader-secret-value");
        token.ShouldNotBeNull();

        var parameters = new TokenValidationParameters
        {
            ValidateIssuer = false,
            ValidateAudience = false,
            ValidateIssuerSigningKey = true,
            IssuerSigningKey = new SymmetricSecurityKey(
                Encoding.UTF8.GetBytes("a-completely-different-key-of-sufficient-length")),
        };

        Should.Throw<SecurityTokenSignatureKeyNotFoundException>(
            () => new JwtSecurityTokenHandler().ValidateToken(token.Value, parameters, out _));
    }

    [Theory]
    [InlineData("reader-client", "wrong-secret")]
    [InlineData("unknown-client", "reader-secret-value")]
    [InlineData("reader-client", "")]
    [InlineData("", "reader-secret-value")]
    [InlineData(null, null)]
    [InlineData("reader-client", "reader-secret-valu")]
    [InlineData("reader-client", "reader-secret-value ")]
    public void Issue_returns_null_for_bad_credentials(string? clientId, string? clientSecret)
    {
        CreateService().Issue(clientId, clientSecret).ShouldBeNull();
    }

    [Fact]
    public void Issue_is_case_sensitive_about_the_client_id()
    {
        CreateService().Issue("READER-CLIENT", "reader-secret-value").ShouldBeNull();
    }

    [Fact]
    public void A_client_configured_with_an_empty_secret_can_never_authenticate()
    {
        var options = new AuthOptions
        {
            Issuer = Options.Issuer,
            Audience = Options.Audience,
            SigningKey = SigningKey,
            Clients = { new ClientCredentialOptions { ClientId = "broken", ClientSecret = string.Empty } },
        };
        var service = new JwtAccessTokenService(
            Microsoft.Extensions.Options.Options.Create(options),
            NullLogger<JwtAccessTokenService>.Instance);

        service.Issue("broken", string.Empty).ShouldBeNull();
        service.Issue("broken", "anything").ShouldBeNull();
    }

    [Fact]
    public void Every_token_has_its_own_identifier()
    {
        var service = CreateService();

        var first = service.Issue("reader-client", "reader-secret-value")!;
        var second = service.Issue("reader-client", "reader-secret-value")!;

        var handler = new JwtSecurityTokenHandler();
        var firstJti = handler.ReadJwtToken(first.Value).Id;
        var secondJti = handler.ReadJwtToken(second.Value).Id;

        firstJti.ShouldNotBeNullOrWhiteSpace();
        secondJti.ShouldNotBe(firstJti);
    }
}
