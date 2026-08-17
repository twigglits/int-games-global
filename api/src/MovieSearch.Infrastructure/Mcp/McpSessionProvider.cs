using System.Diagnostics.CodeAnalysis;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using ModelContextProtocol.Client;
using ModelContextProtocol.Protocol;
using MovieSearch.Domain.Exceptions;
using MovieSearch.Infrastructure.Configuration;

namespace MovieSearch.Infrastructure.Mcp;

/// <summary>Supplies a live MCP session to the catalogue implementation.</summary>
public interface IMcpSessionProvider : IAsyncDisposable
{
    /// <summary>Return a connected MCP client, opening a session if needed.</summary>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>A client whose session is open.</returns>
    Task<McpClient> GetClientAsync(CancellationToken cancellationToken);

    /// <summary>Drop the current session so that the next call opens a new one.</summary>
    /// <returns>A task that completes when the session is closed.</returns>
    Task InvalidateAsync();
}

/// <summary>
/// Owns the single MCP session the API uses.
/// </summary>
/// <remarks>
/// An MCP session is stateful: the client and the server negotiate once and then
/// exchange messages over the same connection. Opening one per request would pay
/// that handshake every time, so the session is created once and shared.
///
/// A shared session must also survive the server restarting. Every call checks
/// whether the session has ended and reopens it, and a failed tool call asks for
/// the session to be dropped. One semaphore serialises creation, so a burst of
/// requests arriving on a cold start opens one session rather than fifty.
/// </remarks>
/// <param name="options">MCP settings.</param>
/// <param name="httpClientFactory">
/// Factory for the transport's HTTP client. Using the factory is what puts the
/// outgoing request on the current trace, so the <c>traceparent</c> header
/// reaches the Python server and the two services share one trace.
/// </param>
/// <param name="loggerFactory">Logger factory handed to the MCP SDK.</param>
/// <param name="logger">Logger.</param>
public sealed class McpSessionProvider(
    IOptions<McpOptions> options,
    IHttpClientFactory httpClientFactory,
    ILoggerFactory loggerFactory,
    ILogger<McpSessionProvider> logger) : IMcpSessionProvider
{
    /// <summary>Name of the HTTP client used by the MCP transport.</summary>
    public const string HttpClientName = "mcp";

    private readonly SemaphoreSlim _gate = new(1, 1);
    private readonly McpOptions _options = options.Value;
    private McpClient? _client;
    private bool _disposed;

    /// <inheritdoc />
    public async Task<McpClient> GetClientAsync(CancellationToken cancellationToken)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);

        var existing = _client;
        if (IsUsable(existing))
        {
            return existing;
        }

        await _gate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            // Another caller may have opened a session while this one waited.
            if (IsUsable(_client))
            {
                return _client;
            }

            await CloseAsync().ConfigureAwait(false);
            _client = await ConnectAsync(cancellationToken).ConfigureAwait(false);
            return _client;
        }
        finally
        {
            _gate.Release();
        }
    }

    /// <inheritdoc />
    public async Task InvalidateAsync()
    {
        if (_disposed)
        {
            return;
        }

        await _gate.WaitAsync().ConfigureAwait(false);
        try
        {
            await CloseAsync().ConfigureAwait(false);
        }
        finally
        {
            _gate.Release();
        }
    }

    /// <inheritdoc />
    public async ValueTask DisposeAsync()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;
        await CloseAsync().ConfigureAwait(false);
        _gate.Dispose();
    }

    private static bool IsUsable([NotNullWhen(true)] McpClient? client) =>
        client is not null && !client.Completion.IsCompleted;

    private async Task<McpClient> ConnectAsync(CancellationToken cancellationToken)
    {
        var transportOptions = new HttpClientTransportOptions
        {
            Endpoint = _options.Endpoint,
            TransportMode = string.Equals(_options.Transport, "sse", StringComparison.OrdinalIgnoreCase)
                ? HttpTransportMode.Sse
                : HttpTransportMode.StreamableHttp,
            ConnectionTimeout = TimeSpan.FromSeconds(_options.ConnectTimeoutSeconds),
            Name = "movie-search-mcp",
        };

        // The HttpClient comes from the factory and is owned by it, so
        // ownsHttpClient is false and the transport must not dispose it.
        var httpClient = httpClientFactory.CreateClient(HttpClientName);
        var transport = new HttpClientTransport(transportOptions, httpClient, loggerFactory, ownsHttpClient: false);

        var clientOptions = new McpClientOptions
        {
            ClientInfo = new Implementation
            {
                Name = "MovieSearch.Api",
                Version = typeof(McpSessionProvider).Assembly.GetName().Version?.ToString() ?? "1.0.0",
            },
            InitializationTimeout = TimeSpan.FromSeconds(_options.ConnectTimeoutSeconds),
        };

        try
        {
            var client = await McpClient
                .CreateAsync(transport, clientOptions, loggerFactory, cancellationToken)
                .ConfigureAwait(false);

            logger.LogInformation(
                "Opened an MCP session to {Endpoint} using the {Transport} transport. Server: {ServerName}",
                _options.Endpoint,
                _options.Transport,
                client.ServerInfo?.Name);
            return client;
        }
        catch (Exception exception) when (exception is not OperationCanceledException)
        {
            throw new MovieCatalogUnavailableException(
                $"Could not open an MCP session to {_options.Endpoint}.",
                exception);
        }
    }

    private async Task CloseAsync()
    {
        var client = _client;
        _client = null;
        if (client is null)
        {
            return;
        }

        try
        {
            await client.DisposeAsync().ConfigureAwait(false);
        }
        catch (Exception exception)
        {
            // A session that is already gone cannot be closed cleanly, and that
            // is not a reason to fail the request that is reopening it.
            logger.LogDebug(exception, "Closing the previous MCP session did not complete cleanly.");
        }
    }
}
