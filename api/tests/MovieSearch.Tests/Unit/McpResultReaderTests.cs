using System.Text.Json;
using ModelContextProtocol.Protocol;
using MovieSearch.Domain.Exceptions;
using MovieSearch.Infrastructure.Mcp;

namespace MovieSearch.Tests.Unit;

/// <summary>
/// The MCP server wraps a list or a scalar in a `result` property and returns a
/// model unwrapped. Both shapes must map onto the same domain types.
/// </summary>
public class McpResultReaderTests
{
    private static CallToolResult Result(string json, bool isError = false) => new()
    {
        StructuredContent = JsonDocument.Parse(json).RootElement.Clone(),
        IsError = isError,
    };

    [Fact]
    public void A_wrapped_list_is_unwrapped()
    {
        var result = Result("""{"result":["Drama","Comedy"]}""");

        McpResultReader.Read<List<string>>(result, "list_genres").ShouldBe(["Drama", "Comedy"]);
    }

    [Fact]
    public void A_wrapped_null_reads_as_null()
    {
        McpResultReader.Read<McpMovieProbe>(Result("""{"result":null}"""), "get_movie_by_title")
            .ShouldBeNull();
    }

    [Fact]
    public void An_unwrapped_object_is_read_as_it_stands()
    {
        var result = Result("""{"total_movies":3200,"embedding_dimension":768}""");

        var stats = McpResultReader.ReadRequired<StatsProbe>(result, "get_dataset_stats");

        stats.TotalMovies.ShouldBe(3200);
        stats.EmbeddingDimension.ShouldBe(768);
    }

    [Fact]
    public void An_object_with_more_than_one_property_is_never_unwrapped()
    {
        // A payload that happens to carry a `result` property beside others is a
        // model, not a wrapper.
        var result = Result("""{"result":1,"total_movies":7,"embedding_dimension":768}""");

        McpResultReader.ReadRequired<StatsProbe>(result, "get_dataset_stats").TotalMovies.ShouldBe(7);
    }

    [Fact]
    public void An_error_result_is_reported_with_the_tool_message()
    {
        var result = new CallToolResult
        {
            IsError = true,
            Content = { new TextContentBlock { Text = "movie_id must be a UUID" } },
        };

        Should.Throw<MovieCatalogUnavailableException>(
                () => McpResultReader.Read<List<string>>(result, "get_similar_movies"))
            .Message.ShouldContain("movie_id must be a UUID");
    }

    [Fact]
    public void An_error_result_with_no_content_still_reports_the_tool_name()
    {
        var result = new CallToolResult { IsError = true };

        Should.Throw<MovieCatalogUnavailableException>(
                () => McpResultReader.Read<List<string>>(result, "list_genres"))
            .Message.ShouldContain("list_genres");
    }

    [Fact]
    public void A_missing_payload_is_reported_rather_than_returned_as_null()
    {
        var result = new CallToolResult();

        Should.Throw<MovieCatalogUnavailableException>(
                () => McpResultReader.Read<List<string>>(result, "list_genres"))
            .Message.ShouldContain("no structured content");
    }

    [Fact]
    public void ReadRequired_rejects_a_null_payload()
    {
        Should.Throw<MovieCatalogUnavailableException>(
                () => McpResultReader.ReadRequired<StatsProbe>(
                    Result("""{"result":null}"""),
                    "get_dataset_stats"))
            .Message.ShouldContain("no value where one is required");
    }

    [Fact]
    public void A_payload_of_the_wrong_shape_is_reported_as_unreadable()
    {
        var result = Result("""{"result":"not an object"}""");

        Should.Throw<MovieCatalogUnavailableException>(
                () => McpResultReader.Read<StatsProbe>(result, "get_dataset_stats"))
            .Message.ShouldContain("cannot read");
    }

    // Small mirrors of the internal wire types, used because the real ones are
    // internal to the infrastructure project.
    public sealed record McpMovieProbe(Guid Id, string Title);

    public sealed record StatsProbe
    {
        public int TotalMovies { get; init; }

        public int EmbeddingDimension { get; init; }
    }
}
