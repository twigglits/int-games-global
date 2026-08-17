using System.Diagnostics;
using System.Diagnostics.Metrics;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using ModelContextProtocol;
using ModelContextProtocol.Protocol;
using MovieSearch.Domain.Abstractions;
using MovieSearch.Domain.Entities;
using MovieSearch.Domain.Exceptions;
using MovieSearch.Domain.ValueObjects;
using MovieSearch.Infrastructure.Configuration;

namespace MovieSearch.Infrastructure.Mcp;

/// <summary>Names of the tools the MCP server publishes.</summary>
public static class McpToolNames
{
    /// <summary>Semantic search with optional metadata filters.</summary>
    public const string SearchByDescription = "search_movies_by_description";

    /// <summary>Exact or approximate title lookup.</summary>
    public const string GetByTitle = "get_movie_by_title";

    /// <summary>Lookup by identifier.</summary>
    public const string GetById = "get_movie_by_id";

    /// <summary>Nearest neighbours of a movie.</summary>
    public const string GetSimilar = "get_similar_movies";

    /// <summary>Distinct genres.</summary>
    public const string ListGenres = "list_genres";

    /// <summary>Dataset statistics.</summary>
    public const string GetStats = "get_dataset_stats";
}

/// <summary>
/// The catalogue port, implemented over MCP.
/// </summary>
/// <remarks>
/// This is the only type in the solution that knows the MCP tool names and their
/// argument shapes. Everything above it works with
/// <see cref="IMovieCatalog"/> and domain entities.
/// </remarks>
/// <param name="sessions">Supplier of the shared MCP session.</param>
/// <param name="options">MCP settings.</param>
/// <param name="logger">Logger.</param>
public sealed class McpMovieCatalog(
    IMcpSessionProvider sessions,
    IOptions<McpOptions> options,
    ILogger<McpMovieCatalog> logger) : IMovieCatalog
{
    /// <summary>Name of the activity source that carries the MCP client spans.</summary>
    public const string ActivitySourceName = "MovieSearch.Mcp";

    private static readonly ActivitySource Activities = new(ActivitySourceName);
    private static readonly Meter Meter = new("MovieSearch.Mcp");

    private static readonly Histogram<double> ToolDuration = Meter.CreateHistogram<double>(
        "movie_search.mcp.tool.duration",
        unit: "ms",
        description: "Wall clock time of one MCP tool call made by the API.");

    private static readonly Counter<long> ToolCalls = Meter.CreateCounter<long>(
        "movie_search.mcp.tool.calls",
        description: "MCP tool calls made by the API, by tool name and outcome.");

    private readonly McpOptions _options = options.Value;

    /// <inheritdoc />
    public async Task<IReadOnlyList<Movie>> SearchAsync(
        MovieSearchCriteria criteria,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(criteria);

        var arguments = new Dictionary<string, object?>(StringComparer.Ordinal)
        {
            ["query"] = criteria.Query,
            ["top_k"] = criteria.TopK,
        };
        AddIfPresent(arguments, "genre_filter", criteria.Genre);
        AddIfPresent(arguments, "min_imdb_rating", criteria.MinimumImdbRating);
        AddIfPresent(arguments, "mpaa_rating", criteria.MpaaRating);
        AddIfPresent(arguments, "decade", criteria.Decade);

        var result = await CallAsync(McpToolNames.SearchByDescription, arguments, cancellationToken)
            .ConfigureAwait(false);
        var movies = McpResultReader.Read<List<McpMovie>>(result, McpToolNames.SearchByDescription);
        return movies?.Select(static movie => movie.ToDomain()).ToList() ?? [];
    }

    /// <inheritdoc />
    public async Task<Movie?> GetByIdAsync(Guid id, CancellationToken cancellationToken)
    {
        var arguments = new Dictionary<string, object?>(StringComparer.Ordinal)
        {
            ["movie_id"] = id.ToString(),
        };
        var result = await CallAsync(McpToolNames.GetById, arguments, cancellationToken)
            .ConfigureAwait(false);
        return McpResultReader.Read<McpMovie>(result, McpToolNames.GetById)?.ToDomain();
    }

    /// <inheritdoc />
    public async Task<Movie?> GetByTitleAsync(string title, CancellationToken cancellationToken)
    {
        var arguments = new Dictionary<string, object?>(StringComparer.Ordinal) { ["title"] = title };
        var result = await CallAsync(McpToolNames.GetByTitle, arguments, cancellationToken)
            .ConfigureAwait(false);
        return McpResultReader.Read<McpMovie>(result, McpToolNames.GetByTitle)?.ToDomain();
    }

    /// <inheritdoc />
    public async Task<IReadOnlyList<Movie>> GetSimilarAsync(
        Guid id,
        int topK,
        CancellationToken cancellationToken)
    {
        var movies = await GetSimilarInternalAsync(id, topK, cancellationToken).ConfigureAwait(false);
        return movies ?? throw new MovieNotFoundException(id);
    }

    /// <inheritdoc />
    public async Task<IReadOnlyList<string>> GetGenresAsync(CancellationToken cancellationToken)
    {
        var result = await CallAsync(McpToolNames.ListGenres, arguments: null, cancellationToken)
            .ConfigureAwait(false);
        return McpResultReader.Read<List<string>>(result, McpToolNames.ListGenres) ?? [];
    }

    /// <inheritdoc />
    public async Task<DatasetStatistics> GetStatisticsAsync(CancellationToken cancellationToken)
    {
        var result = await CallAsync(McpToolNames.GetStats, arguments: null, cancellationToken)
            .ConfigureAwait(false);
        return McpResultReader.ReadRequired<McpDatasetStats>(result, McpToolNames.GetStats).ToDomain();
    }

    /// <inheritdoc />
    public async Task<bool> IsAvailableAsync(CancellationToken cancellationToken)
    {
        try
        {
            var client = await sessions.GetClientAsync(cancellationToken).ConfigureAwait(false);
            await client.PingAsync(cancellationToken: cancellationToken).ConfigureAwait(false);
            return true;
        }
        catch (Exception exception) when (exception is not OperationCanceledException)
        {
            logger.LogWarning(exception, "The MCP server did not answer a ping.");
            return false;
        }
    }

    private static void AddIfPresent(Dictionary<string, object?> arguments, string name, object? value)
    {
        if (value is not null)
        {
            arguments[name] = value;
        }
    }

    private async Task<List<Movie>?> GetSimilarInternalAsync(
        Guid id,
        int topK,
        CancellationToken cancellationToken)
    {
        var arguments = new Dictionary<string, object?>(StringComparer.Ordinal)
        {
            ["movie_id"] = id.ToString(),
            ["top_k"] = topK,
        };

        try
        {
            var result = await CallAsync(McpToolNames.GetSimilar, arguments, cancellationToken)
                .ConfigureAwait(false);
            var movies = McpResultReader.Read<List<McpMovie>>(result, McpToolNames.GetSimilar);
            return movies?.Select(static movie => movie.ToDomain()).ToList() ?? [];
        }
        catch (MovieCatalogUnavailableException exception) when (IsUnknownMovie(exception))
        {
            return null;
        }
    }

    private static bool IsUnknownMovie(Exception exception) =>
        exception.Message.Contains("no movie with id", StringComparison.OrdinalIgnoreCase)
        || exception.InnerException?.Message.Contains("no movie with id", StringComparison.OrdinalIgnoreCase) == true;

    private async Task<CallToolResult> CallAsync(
        string toolName,
        IReadOnlyDictionary<string, object?>? arguments,
        CancellationToken cancellationToken)
    {
        using var activity = Activities.StartActivity($"mcp.call/{toolName}", ActivityKind.Client);
        activity?.SetTag("mcp.tool.name", toolName);
        activity?.SetTag("mcp.transport", _options.Transport);
        activity?.SetTag("server.address", _options.Endpoint.Host);

        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(TimeSpan.FromSeconds(_options.RequestTimeoutSeconds));

        var started = Stopwatch.GetTimestamp();
        var outcome = "ok";
        try
        {
            var client = await sessions.GetClientAsync(timeout.Token).ConfigureAwait(false);
            var result = await client
                .CallToolAsync(toolName, arguments ?? new Dictionary<string, object?>(), cancellationToken: timeout.Token)
                .ConfigureAwait(false);

            if (result.IsError == true)
            {
                outcome = "tool_error";
            }

            return result;
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            outcome = "timeout";
            throw new MovieCatalogUnavailableException(
                $"The MCP tool '{toolName}' did not answer within {_options.RequestTimeoutSeconds} seconds.");
        }
        catch (McpException exception)
        {
            outcome = "protocol_error";
            await sessions.InvalidateAsync().ConfigureAwait(false);
            throw new MovieCatalogUnavailableException(
                $"The MCP tool '{toolName}' failed: {exception.Message}",
                exception);
        }
        catch (MovieCatalogUnavailableException)
        {
            outcome = "unavailable";
            throw;
        }
        catch (Exception exception) when (exception is IOException or HttpRequestException)
        {
            outcome = "transport_error";
            await sessions.InvalidateAsync().ConfigureAwait(false);
            throw new MovieCatalogUnavailableException(
                $"The MCP server could not be reached while calling '{toolName}'.",
                exception);
        }
        finally
        {
            var elapsed = Stopwatch.GetElapsedTime(started).TotalMilliseconds;
            var tags = new TagList { { "tool", toolName }, { "outcome", outcome } };
            ToolDuration.Record(elapsed, tags);
            ToolCalls.Add(1, tags);
            activity?.SetTag("mcp.tool.outcome", outcome);
            logger.LogDebug(
                "MCP tool {ToolName} finished with {Outcome} in {ElapsedMilliseconds} ms",
                toolName,
                outcome,
                elapsed);
        }
    }
}
