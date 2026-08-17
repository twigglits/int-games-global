using Microsoft.OpenApi;

namespace MovieSearch.Api.OpenApi;

/// <summary>OpenAPI 3.1 document generation.</summary>
internal static class OpenApiSetup
{
    /// <summary>Name of the published document.</summary>
    public const string DocumentName = "v1";

    /// <summary>Add the OpenAPI document.</summary>
    /// <param name="services">Service collection.</param>
    /// <returns>The same service collection.</returns>
    /// <remarks>
    /// The document is generated from the endpoints themselves and from the XML
    /// documentation comments in the source, which is why every contract type
    /// carries them. A separate hand-written specification would drift from the
    /// code the first time anyone changed a parameter.
    /// </remarks>
    public static IServiceCollection AddMovieSearchOpenApi(this IServiceCollection services)
    {
        services.AddOpenApi(DocumentName, options =>
        {
            options.AddDocumentTransformer((document, _, _) =>
            {
                document.Info = new OpenApiInfo
                {
                    Title = "Intelligent Movie Search API",
                    Version = "1.0.0",
                    Description =
                        "Semantic search over a movie catalogue.\n\n" +
                        "The API translates a natural language query into a vector, narrows the " +
                        "catalogue with the metadata filters supplied, and returns the closest " +
                        "matches with their similarity scores. The search itself runs on a " +
                        "Python MCP server backed by PostgreSQL with pgvector.\n\n" +
                        "**Getting a token.** Every `/api/v1/*` route needs a bearer token. " +
                        "Post your client id and secret to `/auth/token`, then send the returned " +
                        "token as `Authorization: Bearer <token>`.\n\n" +
                        "**Roles.** A `reader` token may search and read movies. A `admin` token " +
                        "may do that and also read `/api/v1/stats`.\n\n" +
                        "**Rate limit.** 60 requests per minute per client. A rejected request " +
                        "answers 429 and carries a `Retry-After` header.",
                    Contact = new OpenApiContact { Name = "Movie Search Platform" },
                    License = new OpenApiLicense { Name = "MIT" },
                };

                document.Components ??= new OpenApiComponents();
                document.Components.SecuritySchemes ??=
                    new Dictionary<string, IOpenApiSecurityScheme>(StringComparer.Ordinal);
                document.Components.SecuritySchemes["bearerAuth"] = new OpenApiSecurityScheme
                {
                    Type = SecuritySchemeType.Http,
                    Scheme = "bearer",
                    BearerFormat = "JWT",
                    Description =
                        "A JWT obtained from `POST /auth/token`. Send it as " +
                        "`Authorization: Bearer <token>`.",
                };

                document.Tags = new HashSet<OpenApiTag>
                {
                    new OpenApiTag
                    {
                        Name = "Authentication",
                        Description = "Obtaining an access token.",
                    },
                    new OpenApiTag
                    {
                        Name = "Movies",
                        Description = "Searching and reading movies.",
                    },
                    new OpenApiTag
                    {
                        Name = "Statistics",
                        Description = "Facts about the loaded dataset. Requires the admin role.",
                    },
                };

                return Task.CompletedTask;
            });

            // Every operation outside /auth needs the bearer scheme. Declaring it
            // per operation would be repeated on every endpoint and would be
            // forgotten on the next one added.
            options.AddOperationTransformer((operation, context, _) =>
            {
                var path = context.Description.RelativePath ?? string.Empty;
                if (path.StartsWith("api/v1", StringComparison.OrdinalIgnoreCase))
                {
                    operation.Security =
                    [
                        new OpenApiSecurityRequirement
                        {
                            [new OpenApiSecuritySchemeReference("bearerAuth")] = [],
                        },
                    ];
                }

                return Task.CompletedTask;
            });

            // Worked examples for every model and every query parameter. See
            // OpenApiExamples for why they are keyed by type.
            options.AddExamples();
        });

        return services;
    }
}
