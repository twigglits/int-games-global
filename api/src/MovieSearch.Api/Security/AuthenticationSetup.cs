using System.Security.Claims;
using System.Text;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.Extensions.Options;
using Microsoft.IdentityModel.Tokens;
using MovieSearch.Api.Endpoints;
using MovieSearch.Application.Auth;
using MovieSearch.Infrastructure.Configuration;

namespace MovieSearch.Api.Security;

/// <summary>JWT bearer authentication and the role policies.</summary>
internal static class AuthenticationSetup
{
    /// <summary>Add JWT bearer authentication and the authorization policies.</summary>
    /// <param name="services">Service collection.</param>
    /// <returns>The same service collection.</returns>
    /// <remarks>
    /// The bearer options are configured through the options system with
    /// <see cref="AuthOptions"/> injected, rather than by building a second
    /// service provider inside the callback. Building a provider there would
    /// create a duplicate set of singletons for the lifetime of the process.
    /// </remarks>
    public static IServiceCollection AddMovieSearchAuthentication(this IServiceCollection services)
    {
        services.AddAuthentication(JwtBearerDefaults.AuthenticationScheme).AddJwtBearer();

        services.AddOptions<JwtBearerOptions>(JwtBearerDefaults.AuthenticationScheme)
            .Configure<IOptions<AuthOptions>, ILoggerFactory>((options, authOptions, loggerFactory) =>
            {
                var auth = authOptions.Value;

                // Keep the claim types as they arrive. The default mapping
                // rewrites `sub` into a long WS-Federation URI, which then has
                // to be undone in the rate limiter and in every log statement.
                options.MapInboundClaims = false;

                options.TokenValidationParameters = new TokenValidationParameters
                {
                    ValidateIssuer = true,
                    ValidIssuer = auth.Issuer,
                    ValidateAudience = true,
                    ValidAudience = auth.Audience,
                    ValidateIssuerSigningKey = true,
                    IssuerSigningKey = new SymmetricSecurityKey(Encoding.UTF8.GetBytes(auth.SigningKey)),
                    ValidateLifetime = true,
                    // The default five minutes lets an expired token keep
                    // working. A one hour token does not need that much slack.
                    ClockSkew = TimeSpan.FromSeconds(30),
                    RoleClaimType = ClaimTypes.Role,
                    NameClaimType = "sub",
                };

                var logger = loggerFactory.CreateLogger("MovieSearch.Api.Authentication");
                options.Events = new JwtBearerEvents
                {
                    OnAuthenticationFailed = context =>
                    {
                        // The reason is useful to an operator and dangerous to a
                        // caller, so it goes to the log and not to the response.
                        logger.LogWarning(
                            context.Exception,
                            "Rejected a bearer token on {Path}.",
                            context.HttpContext.Request.Path);
                        return Task.CompletedTask;
                    },
                };
            });

        services.AddAuthorizationBuilder()
            .AddPolicy(
                AuthorizationPolicies.Reader,
                policy => policy.RequireAuthenticatedUser().RequireRole(Roles.Reader, Roles.Admin))
            .AddPolicy(
                AuthorizationPolicies.Admin,
                policy => policy.RequireAuthenticatedUser().RequireRole(Roles.Admin));

        return services;
    }
}
