using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.OpenApi;
using Microsoft.OpenApi;
using MovieSearch.Api.Contracts;

namespace MovieSearch.Api.OpenApi;

/// <summary>
/// Worked examples for every model and every query parameter in the document.
/// </summary>
/// <remarks>
/// The generator infers types and descriptions from the source, but it cannot
/// invent a plausible value. A reader opening Swagger UI wants to see what a
/// real answer looks like before sending a request, and "string" does not tell
/// them that <c>budget_tier</c> is one of four words rather than free text.
///
/// The examples are keyed by contract type rather than by schema name, so
/// renaming a record moves its example with it instead of silently orphaning it.
/// </remarks>
internal static class OpenApiExamples
{
    /// <summary>Identifier used consistently across the examples, so they read as one story.</summary>
    private const string MovieId = "3f1b9c48-1c2e-4a5f-9f3a-6d1c0b2e7a41";

    /// <summary>One example per contract type.</summary>
    private static readonly Dictionary<Type, Func<JsonNode>> Examples =
        new Dictionary<Type, Func<JsonNode>>
        {
            [typeof(MovieResponse)] = Movie,
            [typeof(SearchFilters)] = Filters,
            [typeof(SearchResponse)] = () => new JsonObject
            {
                ["query"] = "sci-fi films directed by James Cameron",
                ["count"] = 1,
                ["top_k"] = 10,
                ["filters"] = Filters(),
                ["cached"] = false,
                ["took_ms"] = 118.4,
                ["results"] = new JsonArray(Movie()),
            },
            [typeof(GenresResponse)] = () => new JsonObject
            {
                ["count"] = 4,
                ["genres"] = new JsonArray("Drama", "Comedy", "Action", "Adventure"),
            },
            [typeof(SimilarMoviesResponse)] = () => new JsonObject
            {
                ["movie_id"] = MovieId,
                ["count"] = 1,
                ["results"] = new JsonArray(Movie()),
            },
            [typeof(GenreCountResponse)] = () => new JsonObject
            {
                ["genre"] = "Drama",
                ["count"] = 789,
            },
            [typeof(DecadeCountResponse)] = () => new JsonObject
            {
                ["decade"] = 1990,
                ["count"] = 612,
            },
            [typeof(StatsResponse)] = () => new JsonObject
            {
                ["total_movies"] = 3200,
                ["movies_with_embeddings"] = 3200,
                ["distinct_genres"] = 13,
                ["distinct_directors"] = 1452,
                ["distinct_distributors"] = 172,
                ["earliest_release_year"] = 1915,
                ["latest_release_year"] = 2011,
                ["average_imdb_rating"] = 6.28,
                ["average_rt_rating"] = 53.7,
                ["median_production_budget"] = 25000000,
                ["total_worldwide_gross"] = 285000000000,
                ["movies_per_genre"] = new JsonArray(new JsonObject
                {
                    ["genre"] = "Drama",
                    ["count"] = 789,
                }),
                ["movies_per_decade"] = new JsonArray(new JsonObject
                {
                    ["decade"] = 1990,
                    ["count"] = 612,
                }),
                ["embedding_model"] = "BAAI/bge-base-en-v1.5",
                ["embedding_dimension"] = 768,
                ["pipeline_version"] = "1.0.0",
                ["last_updated"] = "2026-08-17T09:14:22+00:00",
            },
            [typeof(TokenRequest)] = () => new JsonObject
            {
                ["client_id"] = "reader-client",
                ["client_secret"] = "reader-secret-change-me",
                ["grant_type"] = "client_credentials",
            },
            [typeof(TokenResponse)] = () => new JsonObject
            {
                // Deliberately truncated. A copyable token in a public document
                // is an invitation to paste it somewhere it should not go.
                ["access_token"] = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJyZWFkZXIt...",
                ["token_type"] = "Bearer",
                ["expires_in"] = 3600,
                ["roles"] = new JsonArray("reader"),
            },

            // Every failure on every route answers in this shape, so the example
            // shows a real validation failure rather than an abstract one.
            [typeof(ProblemDetails)] = () => new JsonObject
            {
                ["type"] = "https://datatracker.ietf.org/doc/html/rfc9110#section-15.5.1",
                ["title"] = "Invalid request",
                ["status"] = 400,
                ["detail"] = "top_k must be between 1 and 50.",
                ["instance"] = "/api/v1/movies/search",
                // Extensions the API adds: which parameter was wrong, and the
                // trace to quote when reporting the failure.
                ["parameter"] = "top_k",
                ["traceId"] = "00-e79e5b5e8f35cb27aa25fbdd351befff-991094dec4ca84c6-01",
            },
        };

    /// <summary>Example values for the query parameters, keyed by the name on the wire.</summary>
    private static readonly Dictionary<string, JsonNode> ParameterExamples =
        new Dictionary<string, JsonNode>(StringComparer.Ordinal)
        {
            ["q"] = JsonValue.Create("sci-fi films directed by James Cameron")!,
            ["top_k"] = JsonValue.Create(10)!,
            ["genre"] = JsonValue.Create("Action")!,
            ["min_imdb_rating"] = JsonValue.Create(7.5)!,
            ["mpaa_rating"] = JsonValue.Create("PG-13")!,
            ["decade"] = JsonValue.Create(1990)!,
            ["id"] = JsonValue.Create(MovieId)!,
        };

    /// <summary>Attach the examples to schemas, parameters and error responses.</summary>
    /// <param name="options">The OpenAPI options being configured.</param>
    public static void AddExamples(this OpenApiOptions options)
    {
        ArgumentNullException.ThrowIfNull(options);

        options.AddSchemaTransformer((schema, context, _) =>
        {
            if (Examples.TryGetValue(context.JsonTypeInfo.Type, out var build))
            {
                schema.Example = build();
            }

            return Task.CompletedTask;
        });

        options.AddOperationTransformer((operation, _, _) =>
        {
            foreach (var parameter in operation.Parameters ?? [])
            {
                if (parameter is OpenApiParameter concrete
                    && concrete.Name is { } name
                    && ParameterExamples.TryGetValue(name, out var example))
                {
                    concrete.Example = example.DeepClone();
                }
            }

            return Task.CompletedTask;
        });
    }

    /// <summary>A single movie, used on its own and inside the collection responses.</summary>
    private static JsonObject Movie() => new JsonObject
    {
        ["id"] = MovieId,
        ["title"] = "Titanic",
        ["release_date"] = "1997-12-19",
        ["release_year"] = 1997,
        ["decade"] = 1990,
        ["major_genre"] = "Drama",
        ["creative_type"] = "Historical Fiction",
        ["source"] = "Original Screenplay",
        ["mpaa_rating"] = "PG-13",
        ["director"] = "James Cameron",
        ["distributor"] = "Paramount Pictures",
        ["running_time_min"] = 194,
        ["production_budget"] = 200000000,
        ["us_gross"] = 600788188,
        ["worldwide_gross"] = 1842879955,
        ["imdb_rating"] = 7.4,
        ["imdb_votes"] = 654000,
        ["rt_rating"] = 88,
        ["budget_tier"] = "blockbuster",
        ["blockbuster_flag"] = true,
        ["rating_score_delta"] = 14.0,
        // Empty here on purpose: this row needed no imputation. A row that did
        // would name the fields, which is what makes the array worth returning.
        ["imputed_fields"] = new JsonArray(),
        ["similarity"] = 0.8731,
    };

    /// <summary>The filters applied to the example search.</summary>
    private static JsonObject Filters() => new JsonObject
    {
        ["genre"] = null,
        ["min_imdb_rating"] = null,
        ["mpaa_rating"] = null,
        ["decade"] = null,
    };
}
