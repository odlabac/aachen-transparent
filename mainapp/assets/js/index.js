import style from '../css/mainapp.scss';

import HomeMap from "./HomeMap";
import SearchWidget from "./SearchWidget";
import SearchForm from "./SearchForm";

window.jQuery = require('jquery');

$(function () {
    $(".js-home-map").each(function () {
        new HomeMap($(this));
    });

    $(".search-autocomplete input").each(function () {
        new SearchWidget($, $(this));
    });
    $(".detailed-searchform").each(function() {
        new SearchForm($, $(this));
    })
});

let endlessScrollEnded = false;
let isLoading = false;

// Endless scrolling for search results
// https://stackoverflow.com/a/4842226/3549270
function checkAndLoad() {
    if (isLoading) {
        return;
    }
    if ($(window).scrollTop() >= $(document).height() - $(window).height() - 500) {
        isLoading = true;
        let url = $("#start-endless-scroll").data("url") + "?after=" + $("#endless-scroll-target").find("> li").length;
        $.get(url, function (data) {
            let $data = $(data);
            if ($data.length > 0) {
                $data.appendTo("#endless-scroll-target");
            } else {
                endlessScrollEnded = true;
            }
            isLoading = false;
        });
    }
}

let scrollListener = function () {
    $(window).one("scroll", function () {
        checkAndLoad();
        if (!endlessScrollEnded) {
            setTimeout(scrollListener, 100);
        }
    });
};

$(function () {
    $("#start-endless-scroll").click(function () {
        $("#start-endless-scroll").hide();
        checkAndLoad();
        scrollListener();
    });
});