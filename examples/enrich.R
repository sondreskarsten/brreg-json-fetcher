library(dplyr)
library(data.table)
library(jsonlite)

siste_datarelease <- function(repo = "sondreskarsten/regnskapsregisteret-dataset",
                              api_url = sprintf("https://api.github.com/repos/%s/releases?per_page=100", repo)) {
  releases <- fromJSON(api_url, simplifyDataFrame = TRUE) |>
    as_tibble() |>
    filter(!draft, !prerelease, startsWith(tag_name, "data-")) |>
    arrange(desc(published_at))
  if (nrow(releases) == 0) stop("Fant ingen publisert data-release i ", repo, call. = FALSE)
  releases$tag_name[[1]]
}

release_manifest <- function(base_url) {
  fromJSON(paste0(base_url, "/manifest.json"), simplifyVector = FALSE)
}

les_regnskapsdel <- function(url, orgnr, typer, kolonner, timeout = 3600) {
  sti <- tempfile(fileext = ".csv")
  gammel <- options(timeout = max(timeout, getOption("timeout")))
  on.exit({
    unlink(sti)
    options(gammel)
  }, add = TRUE)
  download.file(url, sti, mode = "wb", quiet = TRUE)
  del <- fread(
    sti,
    select = kolonner,
    colClasses = list(character = c("_meta.orgnr", "journalnr")),
    encoding = "UTF-8",
    showProgress = FALSE
  )
  del[`_meta.orgnr` %chin% orgnr & regnskapstype %chin% typer]
}

regnskap_for_orgnr <- function(orgnr = c("923609016", "926412922", "926413252"),
                               tag = NULL,
                               regnskapstype = "SELSKAP",
                               columns = c(
                                 fra_dato = "regnskapsperiode.fraDato",
                                 til_dato = "regnskapsperiode.tilDato",
                                 valuta = "valuta",
                                 driftsinntekter = "resultatregnskapResultat.driftsresultat.driftsinntekter.sumDriftsinntekter",
                                 driftsresultat = "resultatregnskapResultat.driftsresultat.driftsresultat",
                                 aarsresultat = "resultatregnskapResultat.aarsresultat",
                                 sum_eiendeler = "eiendeler.sumEiendeler",
                                 sum_egenkapital = "egenkapitalGjeld.egenkapital.sumEgenkapital"
                               ),
                               repo = "sondreskarsten/regnskapsregisteret-dataset",
                               base_url = sprintf("https://github.com/%s/releases/download/%s", repo, tag)) {
  tag <- tag %||% siste_datarelease(repo)
  orgnr <- unique(as.character(orgnr))
  typer <- regnskapstype %||% c("SELSKAP", "KONSERN")
  nokler <- c(orgnr = "_meta.orgnr", regnskapstype = "regnskapstype", regnskapsaar = "_meta.fiscal_year", journalnr = "journalnr")
  navn <- if (is.null(names(columns))) columns else ifelse(names(columns) == "", columns, names(columns))
  utvalg <- c(nokler, setNames(columns, navn))
  utvalg <- utvalg[!duplicated(utvalg)]
  filer <- release_manifest(base_url)$dataset$accounts$files |> unlist()
  paste0(base_url, "/", filer) |>
    lapply(les_regnskapsdel, orgnr = orgnr, typer = typer, kolonner = unname(utvalg)) |>
    rbindlist(use.names = TRUE) |>
    as_tibble() |>
    select(all_of(utvalg)) |>
    mutate(across(where(\(x) inherits(x, "IDate")), as.Date)) |>
    arrange(orgnr, regnskapstype, regnskapsaar)
}

regnskap_for_orgnr()
