namespace MovieSearch.Domain.Exceptions;

/// <summary>
/// Raised when a caller supplies a search input the domain rejects. The API maps
/// it to HTTP 400 with the offending parameter named.
/// </summary>
public sealed class InvalidSearchCriteriaException : Exception
{
    /// <summary>Create the exception.</summary>
    /// <param name="parameterName">Query parameter that was wrong.</param>
    /// <param name="message">What is wrong with it, in a sentence.</param>
    public InvalidSearchCriteriaException(string parameterName, string message)
        : base(message) => ParameterName = parameterName;

    /// <summary>Create the exception with no named parameter.</summary>
    /// <param name="message">What is wrong, in a sentence.</param>
    public InvalidSearchCriteriaException(string message)
        : base(message) => ParameterName = string.Empty;

    /// <summary>Create the exception with an inner cause.</summary>
    /// <param name="message">What is wrong, in a sentence.</param>
    /// <param name="innerException">The cause.</param>
    public InvalidSearchCriteriaException(string message, Exception innerException)
        : base(message, innerException) => ParameterName = string.Empty;

    /// <summary>Name of the query parameter that failed validation.</summary>
    public string ParameterName { get; }
}

/// <summary>
/// Raised when a movie identifier is not in the catalogue. The API maps it to
/// HTTP 404.
/// </summary>
public sealed class MovieNotFoundException : Exception
{
    /// <summary>Create the exception for one identifier.</summary>
    /// <param name="id">The unknown identifier.</param>
    public MovieNotFoundException(Guid id)
        : base($"No movie with id {id}.") => Id = id;

    /// <summary>Create the exception.</summary>
    /// <param name="message">Message.</param>
    public MovieNotFoundException(string message)
        : base(message) => Id = Guid.Empty;

    /// <summary>Create the exception with an inner cause.</summary>
    /// <param name="message">Message.</param>
    /// <param name="innerException">The cause.</param>
    public MovieNotFoundException(string message, Exception innerException)
        : base(message, innerException) => Id = Guid.Empty;

    /// <summary>Create the exception with no detail.</summary>
    public MovieNotFoundException()
        : base("No movie with that id.") => Id = Guid.Empty;

    /// <summary>The identifier that was not found.</summary>
    public Guid Id { get; }
}

/// <summary>
/// Raised when the movie catalogue cannot answer. The API maps it to HTTP 502,
/// because the fault is behind this service rather than in the request.
/// </summary>
public sealed class MovieCatalogUnavailableException : Exception
{
    /// <summary>Create the exception.</summary>
    /// <param name="message">What failed, in a sentence.</param>
    public MovieCatalogUnavailableException(string message)
        : base(message)
    {
    }

    /// <summary>Create the exception with an inner cause.</summary>
    /// <param name="message">What failed, in a sentence.</param>
    /// <param name="innerException">The cause.</param>
    public MovieCatalogUnavailableException(string message, Exception innerException)
        : base(message, innerException)
    {
    }

    /// <summary>Create the exception with no message.</summary>
    public MovieCatalogUnavailableException()
        : base("The movie catalogue is unavailable.")
    {
    }
}
