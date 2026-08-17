# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# .NET 10 Web API image.
#
# The build restores against the project files first, so a source-only change
# reuses the cached restore layer instead of downloading every package again.
# ---------------------------------------------------------------------------
FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build

ENV DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    DOTNET_NOLOGO=1 \
    DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1

WORKDIR /src

# Restore layer: only the files that decide the dependency graph.
COPY MovieSearch.sln Directory.Build.props global.json ./
COPY src/MovieSearch.Domain/MovieSearch.Domain.csproj             src/MovieSearch.Domain/
COPY src/MovieSearch.Application/MovieSearch.Application.csproj   src/MovieSearch.Application/
COPY src/MovieSearch.Infrastructure/MovieSearch.Infrastructure.csproj src/MovieSearch.Infrastructure/
COPY src/MovieSearch.Api/MovieSearch.Api.csproj                   src/MovieSearch.Api/
COPY tests/MovieSearch.Tests/MovieSearch.Tests.csproj             tests/MovieSearch.Tests/
RUN dotnet restore MovieSearch.sln

# Build layer.
COPY . .
RUN dotnet publish src/MovieSearch.Api/MovieSearch.Api.csproj \
        --configuration Release \
        --no-restore \
        --output /app/publish


# ---------------------------------------------------------------------------
FROM mcr.microsoft.com/dotnet/aspnet:10.0 AS runtime

ENV ASPNETCORE_URLS=http://+:8080 \
    DOTNET_RUNNING_IN_CONTAINER=true \
    DOTNET_gcServer=1

# curl is used by the container health check. The image ships neither curl nor
# wget, so it is installed here and nothing else is.
# The .NET images already ship a non-root `app` user at uid 1000, the Python
# images do not. Creating it only when it is absent keeps one recipe for both.
RUN apt-get update \
    && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/* \
    && (getent group app >/dev/null || groupadd --gid 1000 app) \
    && (getent passwd app >/dev/null || useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash app)

WORKDIR /app
COPY --from=build --chown=app:app /app/publish ./
RUN mkdir -p /app/logs && chown -R app:app /app/logs

USER app
EXPOSE 8080

# The liveness route runs no dependency check, so a container is only restarted
# when the process itself is wedged.
HEALTHCHECK --interval=10s --timeout=5s --start-period=40s --retries=10 \
    CMD curl -fsS http://localhost:8080/health/live || exit 1

ENTRYPOINT ["dotnet", "MovieSearch.Api.dll"]
