using System.ComponentModel.DataAnnotations;

namespace MovieSearch.Infrastructure.Configuration;

/// <summary>How the API reaches the Python MCP server.</summary>
public sealed class McpOptions
{
    /// <summary>Configuration section name.</summary>
    public const string SectionName = "Mcp";

    /// <summary>
    /// Base URL of the MCP server, without the transport path. Example:
    /// <c>http://mcp-server:8000</c>.
    /// </summary>
    [Required]
    public string ServerUrl { get; set; } = "http://mcp-server:8000";

    /// <summary>
    /// Transport to use: <c>sse</c> or <c>http</c>. It must match the transport
    /// the MCP server is running, because the two are mounted on different paths.
    /// </summary>
    [RegularExpression("^(sse|http)$")]
    public string Transport { get; set; } = "sse";

    /// <summary>Seconds allowed for the initial MCP handshake.</summary>
    [Range(1, 300)]
    public int ConnectTimeoutSeconds { get; set; } = 30;

    /// <summary>Seconds allowed for one tool call.</summary>
    [Range(1, 300)]
    public int RequestTimeoutSeconds { get; set; } = 30;

    /// <summary>Path the chosen transport is mounted on.</summary>
    public string TransportPath =>
        string.Equals(Transport, "sse", StringComparison.OrdinalIgnoreCase) ? "/sse" : "/mcp";

    /// <summary>Full URL of the MCP endpoint, including the transport path.</summary>
    public Uri Endpoint => new(new Uri(ServerUrl.TrimEnd('/') + "/"), TransportPath.TrimStart('/'));

    /// <summary>Base URL used for the MCP server's own HTTP health endpoint.</summary>
    public Uri HealthEndpoint => new(new Uri(ServerUrl.TrimEnd('/') + "/"), "health");
}

/// <summary>Response caching for repeated identical queries.</summary>
public sealed class CacheOptions
{
    /// <summary>Configuration section name.</summary>
    public const string SectionName = "Cache";

    /// <summary>Whether the cache is used at all.</summary>
    public bool Enabled { get; set; } = true;

    /// <summary>
    /// How long a cached answer stays fresh. The catalogue only changes when the
    /// pipeline runs, so a short time to live costs nothing in correctness and
    /// removes an embedding call plus a vector scan from every repeat query.
    /// </summary>
    [Range(1, 86400)]
    public int TtlSeconds { get; set; } = 60;

    /// <summary>Upper bound on the number of cached entries.</summary>
    [Range(1, 1000000)]
    public int SizeLimit { get; set; } = 5000;
}

/// <summary>One client allowed to obtain a token.</summary>
public sealed class ClientCredentialOptions
{
    /// <summary>Client identifier.</summary>
    [Required]
    public string ClientId { get; set; } = string.Empty;

    /// <summary>
    /// Client secret. It is supplied by the environment, which in AWS is fed
    /// from Secrets Manager. It is never committed and never logged.
    /// </summary>
    [Required]
    public string ClientSecret { get; set; } = string.Empty;

    /// <summary>Roles granted to a token issued for this client.</summary>
    public IList<string> Roles { get; init; } = [];
}

/// <summary>JWT issuing and validation settings.</summary>
public sealed class AuthOptions
{
    /// <summary>Configuration section name.</summary>
    public const string SectionName = "Auth";

    /// <summary>Issuer claim, and the value the API requires on an incoming token.</summary>
    [Required]
    public string Issuer { get; set; } = "https://movie-search.local";

    /// <summary>Audience claim, and the value the API requires on an incoming token.</summary>
    [Required]
    public string Audience { get; set; } = "movie-search-api";

    /// <summary>
    /// Symmetric signing key. HMAC-SHA256 needs at least 32 bytes, and the
    /// application refuses to start with a shorter one.
    /// </summary>
    [Required]
    [MinLength(32)]
    public string SigningKey { get; set; } = string.Empty;

    /// <summary>Lifetime of an issued token, in minutes.</summary>
    [Range(1, 1440)]
    public int AccessTokenLifetimeMinutes { get; set; } = 60;

    /// <summary>Clients allowed to exchange credentials for a token.</summary>
    public IList<ClientCredentialOptions> Clients { get; init; } = [];
}

/// <summary>Request limits applied to every authenticated caller.</summary>
public sealed class RequestLimitOptions
{
    /// <summary>Configuration section name.</summary>
    public const string SectionName = "RequestLimits";

    /// <summary>Requests one caller may make inside the window.</summary>
    [Range(1, 100000)]
    public int PermitsPerWindow { get; set; } = 60;

    /// <summary>Length of the window in seconds.</summary>
    [Range(1, 3600)]
    public int WindowSeconds { get; set; } = 60;

    /// <summary>How many requests may wait for a permit instead of being rejected.</summary>
    [Range(0, 10000)]
    public int QueueLimit { get; set; } = 0;

    /// <summary>Seconds a request may run before the server abandons it.</summary>
    [Range(1, 600)]
    public int RequestTimeoutSeconds { get; set; } = 30;
}
