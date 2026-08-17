using MovieSearch.Domain.Exceptions;
using MovieSearch.Domain.ValueObjects;

namespace MovieSearch.Tests.Unit;

public class MovieSearchCriteriaTests
{
    [Fact]
    public void Create_trims_the_query()
    {
        var criteria = MovieSearchCriteria.Create("  space horror  ");

        criteria.Query.ShouldBe("space horror");
    }

    [Fact]
    public void Create_uses_the_default_top_k_when_none_is_given()
    {
        MovieSearchCriteria.Create("anything").TopK.ShouldBe(MovieSearchCriteria.DefaultTopK);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData("\t\n")]
    public void Create_rejects_an_empty_query(string? query)
    {
        var thrown = Should.Throw<InvalidSearchCriteriaException>(() => MovieSearchCriteria.Create(query));

        thrown.ParameterName.ShouldBe("q");
    }

    [Fact]
    public void Create_rejects_a_query_that_is_too_long()
    {
        var query = new string('x', MovieSearchCriteria.MaxQueryLength + 1);

        Should.Throw<InvalidSearchCriteriaException>(() => MovieSearchCriteria.Create(query))
            .ParameterName.ShouldBe("q");
    }

    [Theory]
    [InlineData(0)]
    [InlineData(-1)]
    [InlineData(51)]
    [InlineData(int.MaxValue)]
    public void Create_rejects_a_top_k_outside_the_bounds(int topK)
    {
        Should.Throw<InvalidSearchCriteriaException>(() => MovieSearchCriteria.Create("q", topK))
            .ParameterName.ShouldBe("top_k");
    }

    [Theory]
    [InlineData(1)]
    [InlineData(10)]
    [InlineData(50)]
    public void Create_accepts_a_top_k_inside_the_bounds(int topK)
    {
        MovieSearchCriteria.Create("q", topK).TopK.ShouldBe(topK);
    }

    [Theory]
    [InlineData(-0.1)]
    [InlineData(10.1)]
    [InlineData(100)]
    public void Create_rejects_a_rating_outside_zero_to_ten(double rating)
    {
        Should.Throw<InvalidSearchCriteriaException>(
                () => MovieSearchCriteria.Create("q", minimumImdbRating: rating))
            .ParameterName.ShouldBe("min_imdb_rating");
    }

    [Theory]
    [InlineData(1890)]
    [InlineData(2110)]
    public void Create_rejects_a_decade_outside_the_catalogue_range(int decade)
    {
        Should.Throw<InvalidSearchCriteriaException>(() => MovieSearchCriteria.Create("q", decade: decade))
            .ParameterName.ShouldBe("decade");
    }

    [Theory]
    [InlineData(1995)]
    [InlineData(2001)]
    public void Create_rejects_a_decade_that_is_not_a_decade_boundary(int decade)
    {
        // 1995 is not a decade. Accepting it would silently return nothing,
        // because the stored column only ever holds 1990, 2000 and so on.
        Should.Throw<InvalidSearchCriteriaException>(() => MovieSearchCriteria.Create("q", decade: decade))
            .ParameterName.ShouldBe("decade");
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    public void Create_turns_a_blank_filter_into_no_filter(string filter)
    {
        var criteria = MovieSearchCriteria.Create("q", genre: filter, mpaaRating: filter);

        criteria.Genre.ShouldBeNull();
        criteria.MpaaRating.ShouldBeNull();
    }

    [Fact]
    public void Create_trims_the_filters()
    {
        var criteria = MovieSearchCriteria.Create("q", genre: "  Action ", mpaaRating: " R ");

        criteria.Genre.ShouldBe("Action");
        criteria.MpaaRating.ShouldBe("R");
    }

    [Fact]
    public void The_cache_key_ignores_casing_and_padding()
    {
        var first = MovieSearchCriteria.Create(" Space Horror ", 10, "Action", 7.0, "R", 1990);
        var second = MovieSearchCriteria.Create("space horror", 10, "action", 7.0, "r", 1990);

        second.ToCacheKey().ShouldBe(first.ToCacheKey());
    }

    [Fact]
    public void The_cache_key_separates_different_filters()
    {
        var baseline = MovieSearchCriteria.Create("space horror", 10);
        var keys = new[]
        {
            baseline.ToCacheKey(),
            MovieSearchCriteria.Create("space horror", 20).ToCacheKey(),
            MovieSearchCriteria.Create("space horror", 10, genre: "Action").ToCacheKey(),
            MovieSearchCriteria.Create("space horror", 10, minimumImdbRating: 7.0).ToCacheKey(),
            MovieSearchCriteria.Create("space horror", 10, mpaaRating: "R").ToCacheKey(),
            MovieSearchCriteria.Create("space horror", 10, decade: 1990).ToCacheKey(),
            MovieSearchCriteria.Create("other query", 10).ToCacheKey(),
        };

        keys.Distinct(StringComparer.Ordinal).Count().ShouldBe(keys.Length);
    }

    [Fact]
    public void The_cache_key_does_not_confuse_a_filter_with_a_query_that_contains_a_separator()
    {
        // The key joins its parts with '|'. A query containing that character
        // must not be able to impersonate a different set of filters.
        var crafted = MovieSearchCriteria.Create("space|10|action").ToCacheKey();
        var real = MovieSearchCriteria.Create("space", 10, "action").ToCacheKey();

        crafted.ShouldNotBe(real);
    }
}
