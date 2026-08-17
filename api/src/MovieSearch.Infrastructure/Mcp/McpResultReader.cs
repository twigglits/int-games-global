using System.Text.Json;
using ModelContextProtocol.Protocol;
using MovieSearch.Domain.Exceptions;

namespace MovieSearch.Infrastructure.Mcp;

/// <summary>
/// Turns a raw <see cref="CallToolResult"/> into a typed value.
/// </summary>
/// <remarks>
/// Two shapes have to be handled. FastMCP returns a model unwrapped, and wraps
/// anything else in a single <c>result</c> property. Rather than hard-code which
/// tool does which, the reader looks at the payload: an object carrying exactly
/// one <c>result</c> property is unwrapped, anything else is read as it stands.
/// </remarks>
internal static class McpResultReader
{
    private const string WrapperProperty = "result";

    /// <summary>Read a typed value out of a tool result.</summary>
    /// <typeparam name="T">Type to deserialize into.</typeparam>
    /// <param name="result">The tool result.</param>
    /// <param name="toolName">Tool name, used in error messages.</param>
    /// <returns>The deserialized value, or the default when the payload was null.</returns>
    /// <exception cref="MovieCatalogUnavailableException">
    /// When the tool reported an error, returned no structured payload, or
    /// returned a payload that does not match <typeparamref name="T"/>.
    /// </exception>
    public static T? Read<T>(CallToolResult result, string toolName)
    {
        ArgumentNullException.ThrowIfNull(result);

        if (result.IsError == true)
        {
            throw new MovieCatalogUnavailableException(
                $"The MCP tool '{toolName}' reported an error: {DescribeError(result)}");
        }

        if (result.StructuredContent is not { } payload)
        {
            throw new MovieCatalogUnavailableException(
                $"The MCP tool '{toolName}' returned no structured content.");
        }

        var element = Unwrap(payload);
        if (element.ValueKind == JsonValueKind.Null || element.ValueKind == JsonValueKind.Undefined)
        {
            return default;
        }

        try
        {
            return element.Deserialize<T>(McpJson.Options);
        }
        catch (JsonException exception)
        {
            throw new MovieCatalogUnavailableException(
                $"The MCP tool '{toolName}' returned a payload this API cannot read.",
                exception);
        }
    }

    /// <summary>Read a required value, treating null as a protocol failure.</summary>
    /// <typeparam name="T">Type to deserialize into.</typeparam>
    /// <param name="result">The tool result.</param>
    /// <param name="toolName">Tool name, used in error messages.</param>
    /// <returns>The deserialized value.</returns>
    /// <exception cref="MovieCatalogUnavailableException">When the payload was null.</exception>
    public static T ReadRequired<T>(CallToolResult result, string toolName) =>
        Read<T>(result, toolName)
        ?? throw new MovieCatalogUnavailableException(
            $"The MCP tool '{toolName}' returned no value where one is required.");

    private static JsonElement Unwrap(JsonElement payload)
    {
        if (payload.ValueKind != JsonValueKind.Object)
        {
            return payload;
        }

        var propertyCount = 0;
        JsonElement wrapped = default;
        foreach (var property in payload.EnumerateObject())
        {
            propertyCount++;
            if (propertyCount > 1)
            {
                return payload;
            }

            if (!property.NameEquals(WrapperProperty))
            {
                return payload;
            }

            wrapped = property.Value;
        }

        return propertyCount == 1 ? wrapped : payload;
    }

    private static string DescribeError(CallToolResult result)
    {
        var text = result.Content
            .OfType<TextContentBlock>()
            .Select(block => block.Text)
            .FirstOrDefault(static value => !string.IsNullOrWhiteSpace(value));
        return text ?? "no detail supplied";
    }
}
