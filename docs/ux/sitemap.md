# Mapa serwisu

Mapa pokazuje wszystkie publiczne adresy aplikacji oraz wymagany
poziom dostępu.

## Drzewo URL

```mermaid
graph TD
    root["/<br/><i>strona główna / dashboard</i>"]
    health["/health/"]
    admin["/admin/<br/><i>panel Django</i>"]

    subgraph Auth["/auth/"]
      login["/auth/login/"]
      logout["/auth/logout/"]
      register["/auth/register/"]
      activate["/auth/activate/&lt;uid&gt;/&lt;token&gt;/"]
      activation_sent["/auth/activation-sent/"]
      resend["/auth/resend-activation/"]
      profile["/auth/profile/"]
      settings["/auth/settings/"]
      display_name["/auth/display-name/"]
      genres["/auth/genres/"]
      pwreset["/auth/password-reset/"]
      pwreset_done["/auth/password-reset/done/"]
      pwreset_confirm["/auth/reset/&lt;uid&gt;/&lt;token&gt;/"]
      pwreset_complete["/auth/reset/done/"]
    end

    subgraph Movies["/movies/"]
      list["/movies/<br/><i>lista + wyszukiwarka</i>"]
      detail["/movies/&lt;tmdb_id&gt;/"]
      status_act["/movies/&lt;id&gt;/status/<br/><i>POST</i>"]
      rating_act["/movies/&lt;id&gt;/rating/<br/><i>POST</i>"]
      comment_create["/movies/&lt;id&gt;/comments/<br/><i>POST</i>"]
      comment_del["/movies/&lt;id&gt;/comments/&lt;cid&gt;/delete/<br/><i>POST</i>"]
    end

    subgraph Community["/community/"]
      feed["/community/<br/><i>feed znajomych</i>"]
      people["/community/people/"]
      profile_pub["/community/u/&lt;user_id&gt;/<br/><i>publiczny profil</i>"]
      follow_act["/community/people/&lt;user_id&gt;/follow/<br/><i>POST (toggle)</i>"]
    end

    root --> Movies
    root --> Auth
    root --> Community
    detail --> status_act
    detail --> rating_act
    detail --> comment_create
    detail --> comment_del
    people --> follow_act
    people --> profile_pub

    style admin fill:#fde7e9,stroke:#c4314b
    style status_act fill:#fff5d6,stroke:#b08800
    style rating_act fill:#fff5d6,stroke:#b08800
    style comment_create fill:#fff5d6,stroke:#b08800
    style comment_del fill:#fff5d6,stroke:#b08800
    style follow_act fill:#fff5d6,stroke:#b08800
```

## Mapowanie do plików

| Sekcja | Plik URL conf |
|---|---|
| `/` | [`core/urls.py`](https://github.com/agatav13/aster/blob/main/core/urls.py) |
| `/auth/...` | [`accounts/urls.py`](https://github.com/agatav13/aster/blob/main/accounts/urls.py) |
| `/movies/...` | [`movies/urls.py`](https://github.com/agatav13/aster/blob/main/movies/urls.py) |
| `/community/...` | [`community/urls.py`](https://github.com/agatav13/aster/blob/main/community/urls.py) |
| `/admin/`, `/health/`, root include | [`config/urls.py`](https://github.com/agatav13/aster/blob/main/config/urls.py) |

> **Uwaga:** sekcja `/community/` jest w pełni działająca. Feed
> znajomych i profile publiczne są zasilane modelem
> [`community.Follow`](https://github.com/agatav13/aster/blob/main/community/models.py)
> oraz serwisem
> [`build_feed_groups`](https://github.com/agatav13/aster/blob/main/community/services.py),
> który łączy ratingi i statusy „watched" obserwowanych użytkowników.
> Akcja `POST /community/people/<user_id>/follow/` jest idempotentnym
> toggle’em. Kuratorowane listy społecznościowe pozostają na roadmapie.
