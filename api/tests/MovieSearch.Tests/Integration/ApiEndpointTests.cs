using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using MovieSearch.Tests.Fakes;

namespace MovieSearch.Tests.Integration;

public class ApiEndpointTests : IClassFixture<MovieSearchApiFactory>
{
    private readonly MovieSearchApiFactory _factory;

    public ApiEndpointTests(MovieSearchApiFactory factory) => _factory = factory;

    private static CancellationToken Token => TestContext.Current.CancellationToken;

    // --- authentication -----------------------------------------------------

    [Theory]
    [InlineData("/api/v1/movies/search?q=space")]
    [InlineData("/api/v1/movies/genres")]
    [InlineData("/api/v1/movies/8267e750-d59b-4259-a9f6-4025e0d78565")]
    [InlineData("/api/v1/movies/8267e750-d59b-4259-a9f6-4025e0d78565/similar")]
    [InlineData("/api/v1/stats")]
    public async Task Every_v1_route_needs_a_token(string path)
    {
        var response = await _factory.CreateClient().GetAsync(path, Token);

        response.StatusCode.ShouldBe(HttpStatusCode.Unauthorized);
    }

    [Fact]
    public async Task A_forged_token_is_rejected()
    {
        var client = _factory.CreateClient();
        client.DefaultRequestHeaders.Authorization =
            new System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", "not.a.jwt");

        var response = await client.GetAsync("/api/v1/movies/genres", Token);

        response.StatusCode.ShouldBe(HttpStatusCode.Unauthorized);
    }

    [Fact]
    public async Task The_token_endpoint_issues_a_token_for_valid_credentials()
    {
        var response = await _factory.CreateClient().PostAsJsonAsync(
            "/auth/token",
            new
            {
                client_id = MovieSearchApiFactory.ReaderClientId,
                client_secret = MovieSearchApiFactory.ReaderSecret,
                grant_type = "client_credentials",
            },
            Token);

        response.StatusCode.ShouldBe(HttpStatusCode.OK);
        var payload = await response.Content.ReadFromJsonAsync<MovieSearchApiFactory.TokenPayload>(
            MovieSearchApiFactory.Json,
            Token);
        payload.ShouldNotBeNull();
        payload.TokenType.ShouldBe("Bearer");
        payload.ExpiresIn.ShouldBe(3600);
        payload.Roles.ShouldBe(["reader"]);
    }

    [Fact]
    public async Task The_token_endpoint_rejects_a_wrong_secret()
    {
        var response = await _factory.CreateClient().PostAsJsonAsync(
            "/auth/token",
            new { client_id = MovieSearchApiFactory.ReaderClientId, client_secret = "wrong" },
            Token);

        response.StatusCode.ShouldBe(HttpStatusCode.Unauthorized);
    }

    [Fact]
    public async Task The_token_endpoint_rejects_an_unsupported_grant_type()
    {
        var response = await _factory.CreateClient().PostAsJsonAsync(
            "/auth/token",
            new
            {
                client_id = MovieSearchApiFactory.ReaderClientId,
                client_secret = MovieSearchApiFactory.ReaderSecret,
                grant_type = "password",
            },
            Token);

        response.StatusCode.ShouldBe(HttpStatusCode.BadRequest);
    }

    [Fact]
    public async Task An_unknown_client_and_a_wrong_secret_are_answered_the_same_way()
    {
        // Answering differently would let a caller enumerate valid client ids.
        var client = _factory.CreateClient();

        var unknown = await client.PostAsJsonAsync(
            "/auth/token",
            new { client_id = "no-such-client", client_secret = "whatever" },
            Token);
        var wrongSecret = await client.PostAsJsonAsync(
            "/auth/token",
            new { client_id = MovieSearchApiFactory.ReaderClientId, client_secret = "whatever" },
            Token);

        unknown.StatusCode.ShouldBe(wrongSecret.StatusCode);
        (await unknown.Content.ReadAsStringAsync(Token))
            .ShouldBe(await wrongSecret.Content.ReadAsStringAsync(Token));
    }

    // --- search -------------------------------------------------------------

    [Fact]
    public async Task Search_returns_results_and_echoes_the_criteria()
    {
        var client = await _factory.CreateReaderClientAsync();

        var response = await client.GetAsync(
            "/api/v1/movies/search?q=space%20horror&top_k=5&genre=Action&min_imdb_rating=7&mpaa_rating=R&decade=1980",
            Token);

        response.StatusCode.ShouldBe(HttpStatusCode.OK);
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync(Token));
        var root = document.RootElement;
        root.GetProperty("query").GetString().ShouldBe("space horror");
        root.GetProperty("top_k").GetInt32().ShouldBe(5);
        root.GetProperty("count").GetInt32().ShouldBe(1);
        root.GetProperty("filters").GetProperty("genre").GetString().ShouldBe("Action");
        root.GetProperty("filters").GetProperty("decade").GetInt32().ShouldBe(1980);
        root.GetProperty("results")[0].GetProperty("title").GetString().ShouldBe("The Terminator");
        root.GetProperty("results")[0].GetProperty("similarity").GetDouble().ShouldBe(0.81);
    }

    [Fact]
    public async Task Search_uses_snake_case_field_names()
    {
        var client = await _factory.CreateReaderClientAsync();

        var body = await client.GetStringAsync("/api/v1/movies/search?q=anything", Token);

        body.ShouldContain("\"release_year\"");
        body.ShouldContain("\"major_genre\"");
        body.ShouldContain("\"imdb_rating\"");
        body.ShouldNotContain("\"releaseYear\"");
    }

    [Theory]
    [InlineData("/api/v1/movies/search")]
    [InlineData("/api/v1/movies/search?q=")]
    [InlineData("/api/v1/movies/search?q=x&top_k=0")]
    [InlineData("/api/v1/movies/search?q=x&top_k=51")]
    [InlineData("/api/v1/movies/search?q=x&min_imdb_rating=11")]
    [InlineData("/api/v1/movies/search?q=x&decade=1995")]
    public async Task Search_rejects_invalid_criteria_with_a_problem_document(string path)
    {
        var client = await _factory.CreateReaderClientAsync();

        var response = await client.GetAsync(path, Token);

        response.StatusCode.ShouldBe(HttpStatusCode.BadRequest);
        response.Content.Headers.ContentType!.MediaType.ShouldBe("application/problem+json");
        (await response.Content.ReadAsStringAsync(Token)).ShouldContain("traceId");
    }

    [Fact]
    public async Task Search_reports_a_catalogue_failure_as_a_bad_gateway()
    {
        await using var factory = new MovieSearchApiFactory();
        factory.Catalog.SearchThrows =
            new MovieSearch.Domain.Exceptions.MovieCatalogUnavailableException("the MCP server is down");
        var client = await factory.CreateReaderClientAsync();

        var response = await client.GetAsync("/api/v1/movies/search?q=x", Token);

        response.StatusCode.ShouldBe(HttpStatusCode.BadGateway);
    }

    // --- movies -------------------------------------------------------------

    [Fact]
    public async Task A_known_identifier_returns_the_movie()
    {
        var client = await _factory.CreateReaderClientAsync();

        var response = await client.GetAsync($"/api/v1/movies/{FakeMovieCatalog.TerminatorId}", Token);

        response.StatusCode.ShouldBe(HttpStatusCode.OK);
        (await response.Content.ReadAsStringAsync(Token)).ShouldContain("The Terminator");
    }

    [Fact]
    public async Task An_unknown_identifier_returns_not_found()
    {
        await using var factory = new MovieSearchApiFactory();
        factory.Catalog.MovieById = null;
        var client = await factory.CreateReaderClientAsync();

        var response = await client.GetAsync($"/api/v1/movies/{Guid.NewGuid()}", Token);

        response.StatusCode.ShouldBe(HttpStatusCode.NotFound);
    }

    [Fact]
    public async Task An_identifier_that_is_not_a_guid_does_not_match_the_route()
    {
        var client = await _factory.CreateReaderClientAsync();

        var response = await client.GetAsync("/api/v1/movies/not-a-guid", Token);

        response.StatusCode.ShouldBe(HttpStatusCode.NotFound);
    }

    [Fact]
    public async Task Similar_movies_returns_the_neighbours()
    {
        var client = await _factory.CreateReaderClientAsync();

        var response = await client.GetAsync(
            $"/api/v1/movies/{FakeMovieCatalog.TerminatorId}/similar?top_k=3",
            Token);

        response.StatusCode.ShouldBe(HttpStatusCode.OK);
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync(Token));
        document.RootElement.GetProperty("movie_id").GetGuid().ShouldBe(FakeMovieCatalog.TerminatorId);
        document.RootElement.GetProperty("results")[0].GetProperty("title").GetString().ShouldBe("Aliens");
    }

    [Fact]
    public async Task Similar_movies_returns_not_found_for_an_unknown_movie()
    {
        await using var factory = new MovieSearchApiFactory();
        factory.Catalog.SimilarResults = null;
        var client = await factory.CreateReaderClientAsync();

        var response = await client.GetAsync($"/api/v1/movies/{Guid.NewGuid()}/similar", Token);

        response.StatusCode.ShouldBe(HttpStatusCode.NotFound);
    }

    [Theory]
    [InlineData(0)]
    [InlineData(51)]
    public async Task Similar_movies_bounds_top_k(int topK)
    {
        var client = await _factory.CreateReaderClientAsync();

        var response = await client.GetAsync(
            $"/api/v1/movies/{FakeMovieCatalog.TerminatorId}/similar?top_k={topK}",
            Token);

        response.StatusCode.ShouldBe(HttpStatusCode.BadRequest);
    }

    [Fact]
    public async Task Genres_are_listed()
    {
        var client = await _factory.CreateReaderClientAsync();

        var response = await client.GetAsync("/api/v1/movies/genres", Token);

        response.StatusCode.ShouldBe(HttpStatusCode.OK);
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync(Token));
        document.RootElement.GetProperty("count").GetInt32().ShouldBe(3);
        document.RootElement.GetProperty("genres")[0].GetString().ShouldBe("Drama");
    }

    // --- roles ---------------------------------------------------------------

    [Fact]
    public async Task A_reader_token_cannot_read_the_statistics()
    {
        var client = await _factory.CreateReaderClientAsync();

        var response = await client.GetAsync("/api/v1/stats", Token);

        response.StatusCode.ShouldBe(HttpStatusCode.Forbidden);
    }

    [Fact]
    public async Task An_admin_token_can_read_the_statistics()
    {
        var client = await _factory.CreateAdminClientAsync();

        var response = await client.GetAsync("/api/v1/stats", Token);

        response.StatusCode.ShouldBe(HttpStatusCode.OK);
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync(Token));
        document.RootElement.GetProperty("total_movies").GetInt32().ShouldBe(3200);
        document.RootElement.GetProperty("embedding_dimension").GetInt32().ShouldBe(768);
    }

    [Fact]
    public async Task An_admin_token_can_also_search()
    {
        var client = await _factory.CreateAdminClientAsync();

        var response = await client.GetAsync("/api/v1/movies/search?q=anything", Token);

        response.StatusCode.ShouldBe(HttpStatusCode.OK);
    }

    // --- operations -----------------------------------------------------------

    [Fact]
    public async Task The_liveness_probe_ignores_the_dependencies()
    {
        var response = await _factory.CreateClient().GetAsync("/health/live", Token);

        response.StatusCode.ShouldBe(HttpStatusCode.OK);
    }

    [Fact]
    public async Task The_readiness_probe_fails_when_the_mcp_server_is_unreachable()
    {
        // The factory points the MCP settings at a host that does not resolve.
        var response = await _factory.CreateClient().GetAsync("/health/ready", Token);

        response.StatusCode.ShouldBe(HttpStatusCode.ServiceUnavailable);
        (await response.Content.ReadAsStringAsync(Token)).ShouldContain("mcp-server");
    }

    [Fact]
    public async Task The_metrics_endpoint_is_exposed_for_prometheus()
    {
        var response = await _factory.CreateClient().GetAsync("/metrics", Token);

        response.StatusCode.ShouldBe(HttpStatusCode.OK);
        (await response.Content.ReadAsStringAsync(Token)).ShouldContain("http_server_request_duration");
    }

    [Fact]
    public async Task The_openapi_document_is_published()
    {
        var response = await _factory.CreateClient().GetAsync("/openapi/v1.json", Token);

        response.StatusCode.ShouldBe(HttpStatusCode.OK);
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync(Token));
        var root = document.RootElement;
        root.GetProperty("openapi").GetString().ShouldStartWith("3.1");
        root.GetProperty("info").GetProperty("title").GetString().ShouldBe("Intelligent Movie Search API");
        root.GetProperty("paths").TryGetProperty("/api/v1/movies/search", out _).ShouldBeTrue();
        root.GetProperty("paths").TryGetProperty("/auth/token", out _).ShouldBeTrue();
        root.GetProperty("components").GetProperty("securitySchemes")
            .TryGetProperty("bearerAuth", out _).ShouldBeTrue();
    }

    [Fact]
    public async Task Swagger_ui_is_served()
    {
        var response = await _factory.CreateClient().GetAsync("/swagger/index.html", Token);

        response.StatusCode.ShouldBe(HttpStatusCode.OK);
    }
}
