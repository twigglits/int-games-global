using System.Text.Json;
using MovieSearch.Infrastructure.Configuration;
using MovieSearch.Infrastructure.Mcp;

namespace MovieSearch.Tests.Unit;

/// <summary>
/// The payloads below are copied from a live MCP server. If the Python side ever
/// renames a field, these tests fail rather than the field silently becoming
/// null in every API response.
/// </summary>
public class McpContractTests
{
    private const string MoviePayload = """
        {
          "id": "b036a13b-c501-441e-9cd2-c4072938d827",
          "title": "Aliens",
          "release_date": "1986-07-18",
          "release_year": 1986,
          "decade": 1980,
          "major_genre": "Action",
          "creative_type": "Science Fiction",
          "source": "Original Screenplay",
          "mpaa_rating": "R",
          "director": "James Cameron",
          "distributor": "20th Century Fox",
          "running_time_min": 137,
          "production_budget": 17000000,
          "us_gross": 85160248,
          "worldwide_gross": 183316455,
          "imdb_rating": 7.5,
          "imdb_votes": 84,
          "rt_rating": 100,
          "budget_tier": "low",
          "blockbuster_flag": true,
          "rating_score_delta": -25.0,
          "imputed_fields": ["running_time_min"],
          "similarity": 0.603312
        }
        """;

    private const string StatsPayload = """
        {
          "total_movies": 3200,
          "movies_with_embeddings": 3200,
          "distinct_genres": 13,
          "distinct_directors": 800,
          "distinct_distributors": 175,
          "earliest_release_year": 1915,
          "latest_release_year": 2011,
          "average_imdb_rating": 6.28,
          "average_rt_rating": 52.4,
          "median_production_budget": 20000000,
          "total_worldwide_gross": 250000000000,
          "movies_per_genre": [{"genre": "Drama", "count": 789}],
          "movies_per_decade": [{"decade": 1990, "count": 769}],
          "embedding_model": "BAAI/bge-base-en-v1.5",
          "embedding_dimension": 768,
          "pipeline_version": "1.0.0",
          "last_updated": "2026-08-17T08:59:45.840909+00:00"
        }
        """;

    [Fact]
    public void Every_movie_field_maps_onto_the_domain_entity()
    {
        var wire = JsonSerializer.Deserialize<McpMovie>(MoviePayload, McpJson.Options);
        wire.ShouldNotBeNull();

        var movie = wire.ToDomain();

        movie.Id.ShouldBe(new Guid("b036a13b-c501-441e-9cd2-c4072938d827"));
        movie.Title.ShouldBe("Aliens");
        movie.ReleaseDate.ShouldBe(new DateOnly(1986, 7, 18));
        movie.ReleaseYear.ShouldBe(1986);
        movie.Decade.ShouldBe(1980);
        movie.MajorGenre.ShouldBe("Action");
        movie.CreativeType.ShouldBe("Science Fiction");
        movie.Source.ShouldBe("Original Screenplay");
        movie.MpaaRating.ShouldBe("R");
        movie.Director.ShouldBe("James Cameron");
        movie.Distributor.ShouldBe("20th Century Fox");
        movie.RunningTimeMinutes.ShouldBe(137);
        movie.ProductionBudget.ShouldBe(17_000_000);
        movie.UsGross.ShouldBe(85_160_248);
        movie.WorldwideGross.ShouldBe(183_316_455);
        movie.ImdbRating.ShouldBe(7.5);
        movie.ImdbVotes.ShouldBe(84);
        movie.RottenTomatoesRating.ShouldBe(100);
        movie.BudgetTier.ShouldBe("low");
        movie.IsBlockbuster.ShouldBe(true);
        movie.RatingScoreDelta.ShouldBe(-25.0);
        movie.ImputedFields.ShouldBe(["running_time_min"]);
        movie.Similarity.ShouldBe(0.603312);
    }

    [Fact]
    public void A_movie_with_only_a_title_and_an_id_still_maps()
    {
        const string sparse = """{"id":"b036a13b-c501-441e-9cd2-c4072938d827","title":"Sparse"}""";

        var movie = JsonSerializer.Deserialize<McpMovie>(sparse, McpJson.Options)!.ToDomain();

        movie.Title.ShouldBe("Sparse");
        movie.ReleaseDate.ShouldBeNull();
        movie.Director.ShouldBeNull();
        movie.Similarity.ShouldBeNull();
        movie.ImputedFields.ShouldBeEmpty();
    }

    [Fact]
    public void Every_statistics_field_maps_onto_the_domain_entity()
    {
        var wire = JsonSerializer.Deserialize<McpDatasetStats>(StatsPayload, McpJson.Options);
        wire.ShouldNotBeNull();

        var stats = wire.ToDomain();

        stats.TotalMovies.ShouldBe(3200);
        stats.MoviesWithEmbeddings.ShouldBe(3200);
        stats.DistinctGenres.ShouldBe(13);
        stats.DistinctDirectors.ShouldBe(800);
        stats.DistinctDistributors.ShouldBe(175);
        stats.EarliestReleaseYear.ShouldBe(1915);
        stats.LatestReleaseYear.ShouldBe(2011);
        stats.AverageImdbRating.ShouldBe(6.28);
        stats.AverageRottenTomatoesRating.ShouldBe(52.4);
        stats.MedianProductionBudget.ShouldBe(20_000_000);
        stats.TotalWorldwideGross.ShouldBe(250_000_000_000);
        stats.MoviesPerGenre.ShouldHaveSingleItem().Genre.ShouldBe("Drama");
        stats.MoviesPerDecade.ShouldHaveSingleItem().Decade.ShouldBe(1990);
        stats.EmbeddingModel.ShouldBe("BAAI/bge-base-en-v1.5");
        stats.EmbeddingDimension.ShouldBe(768);
        stats.PipelineVersion.ShouldBe("1.0.0");
        stats.LastUpdated.ShouldNotBeNull();
    }

    [Theory]
    [InlineData("sse", "/sse")]
    [InlineData("SSE", "/sse")]
    [InlineData("http", "/mcp")]
    public void The_endpoint_carries_the_path_of_the_chosen_transport(string transport, string path)
    {
        var options = new McpOptions { ServerUrl = "http://mcp-server:8000", Transport = transport };

        options.Endpoint.ToString().ShouldBe($"http://mcp-server:8000{path}");
        options.TransportPath.ShouldBe(path);
    }

    [Fact]
    public void A_trailing_slash_on_the_server_url_does_not_double_up()
    {
        var options = new McpOptions { ServerUrl = "http://mcp-server:8000/", Transport = "sse" };

        options.Endpoint.ToString().ShouldBe("http://mcp-server:8000/sse");
        options.HealthEndpoint.ToString().ShouldBe("http://mcp-server:8000/health");
    }
}
