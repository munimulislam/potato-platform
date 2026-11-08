#!/usr/bin/env Rscript
# fit_blup.R
# Fits a REML/BLUP linear mixed model for ONE trait and writes the results as JSON.
#
# Usage:  Rscript fit_blup.R <input.csv> <output.json>
#
# Input:  CSV with columns variety, experiment_name, value
#         (one row per variety x trial; value = mean of the variety's plots in that trial).
# Model:  statgenGxE::gxeVarComp with trials as environments and one mean per cell:
#             value ~ trial (fixed) + (1 | genotype) (random)
#         The genotype x trial interaction is absorbed into the residual.
# Output: per variety: predicted value (BLUP-based), standard error, reliability;
#         per model: variance components, heritability, convergence, warnings, versions.
#         The JSON is written atomically: to <output>.tmp first, then renamed.

suppressPackageStartupMessages({
  library(statgenSTA)
  library(statgenGxE)
  library(lme4)
  library(jsonlite)
})

write_json_atomic <- function(x, path) {
  tmp <- paste0(path, ".tmp")
  writeLines(toJSON(x, auto_unbox = TRUE, digits = NA, null = "null",
                    na = "null", pretty = TRUE), tmp)
  if (file.exists(path)) unlink(path)          # file.rename does not overwrite on Windows
  if (!file.rename(tmp, path)) stop("Could not write output file: ", path)
}

fit_blup <- function(input_path) {
  dat <- read.csv(input_path, stringsAsFactors = FALSE, check.names = FALSE)

  required <- c("variety", "experiment_name", "value")
  missing_cols <- setdiff(required, names(dat))
  if (length(missing_cols) > 0) {
    stop("Input is missing columns: ", paste(missing_cols, collapse = ", "))
  }
  dat <- dat[!is.na(dat$value), required]
  if (anyDuplicated(dat[c("variety", "experiment_name")]) > 0) {
    stop("Input must have exactly one row per variety x experiment_name.")
  }

  # Collect warnings instead of printing them, so they can be returned in the JSON.
  warnings_seen <- character()
  vc_fit <- withCallingHandlers(
    {
      td <- createTD(data = dat, genotype = "variety", trial = "experiment_name")
      gxeVarComp(TD = td, trait = "value", engine = "lme4")
    },
    warning = function(w) {
      warnings_seen <<- c(warnings_seen, conditionMessage(w))
      invokeRestart("muffleWarning")
    },
    message = function(m) invokeRestart("muffleMessage")
  )

  mod <- vc_fit$fitMod
  if (!inherits(mod, "lmerMod")) {
    stop("Unexpected model class from gxeVarComp: ", paste(class(mod), collapse = ", "))
  }

  # Variance components: first row = genotype, last row = residual.
  comps <- vc(vc_fit)
  if (!("genotype" %in% rownames(comps))) {
    stop("No genotype variance component in the fitted model.")
  }
  sigma2_g <- comps["genotype", "Component"]
  sigma2_e <- comps[nrow(comps), "Component"]

  # Predictions at genotype level (overall mean + BLUP of the genotype effect).
  pred <- predict(vc_fit, predictLevel = "genotype")

  # Prediction error variance (PEV) of each genotype BLUP, from lme4.
  # Note: conditional on the estimated fixed effects and variance components.
  re <- ranef(mod, condVar = TRUE)$genotype
  pev <- as.numeric(attr(re, "postVar")[1, 1, ])
  pev_df <- data.frame(variety = rownames(re), pev = pev, stringsAsFactors = FALSE)

  out <- merge(
    data.frame(variety = as.character(pred$genotype),
               predicted_value = pred$predictedValue,
               stringsAsFactors = FALSE),
    pev_df, by = "variety"
  )
  out$se <- sqrt(out$pev)
  out$reliability <- if (sigma2_g > 0) pmax(0, 1 - out$pev / sigma2_g) else 0
  out$pev <- NULL

  # Entry-mean heritability with the harmonic mean number of trials per variety.
  # Computed here because statgenGxE::herit() uses the median replicates per
  # genotype x trial cell, which is 0 in sparse unbalanced trial series.
  trials_per_variety <- as.numeric(table(dat$variety))
  n_harmonic <- 1 / mean(1 / trials_per_variety)
  heritability <- if (sigma2_g > 0) sigma2_g / (sigma2_g + sigma2_e / n_harmonic) else 0

  conv_messages <- mod@optinfo$conv$lme4$messages
  list(
    status = "ok",
    model = list(
      formula = paste(deparse(formula(mod)), collapse = " "),
      engine = "lme4",
      sigma2_g = sigma2_g,
      sigma2_e = sigma2_e,
      heritability = heritability,
      mean_reliability = mean(out$reliability),
      n_varieties = length(unique(dat$variety)),
      n_trials = length(unique(dat$experiment_name)),
      n_observations = nrow(dat),
      converged = is.null(conv_messages),
      singular = isSingular(mod)
    ),
    predictions = out[order(-out$predicted_value), ],
    warnings = unique(c(warnings_seen, conv_messages)),
    versions = list(
      R = paste(R.version$major, R.version$minor, sep = "."),
      statgenGxE = as.character(packageVersion("statgenGxE")),
      statgenSTA = as.character(packageVersion("statgenSTA")),
      lme4 = as.character(packageVersion("lme4"))
    )
  )
}

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2) {
  cat("Usage: Rscript fit_blup.R <input.csv> <output.json>\n")
  quit(status = 2)
}

result <- tryCatch(
  fit_blup(args[1]),
  error = function(e) list(status = "error", message = conditionMessage(e))
)
write_json_atomic(result, args[2])
quit(status = if (identical(result$status, "ok")) 0 else 1)