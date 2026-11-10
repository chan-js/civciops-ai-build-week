# Base R only. Run from project root: Rscript r/validate_markov.R
# OR open r/CivicOpsResilience.Rproj and source('validate_markov.R').
# This file is provided for RStudio; R is not installed in the build environment.
P <- matrix(c(.82,.16,.02, .18,.63,.19, .05,.25,.70), nrow=3, byrow=TRUE)
stopifnot(all(abs(rowSums(P)-1)<1e-12), all(P>=0))
initial <- c(0,1,0) # deteriorating state at exercise start
three_hour_distribution <- initial %*% P %*% P %*% P
print(three_hour_distribution)
set.seed(42)
samples <- replicate(10000, {
  state <- 2
  for (t in seq_len(3)) state <- sample.int(3, 1, prob=P[state,])
  state
})
print(prop.table(table(factor(samples,levels=1:3))))
root <- if (file.exists('pyproject.toml')) '.' else '..'
input <- file.path(root,'outputs','community_plan.csv')
if (file.exists(input)) {
  plan <- read.csv(input,fileEncoding='UTF-8-BOM')
  stopifnot(all(plan$assigned+plan$unassigned==plan$population))
  print(plan[order(-plan$unassigned),])
} else {
  message('Run python -m disaster_response.cli plan first to inspect a plan CSV.')
}
message('Synthetic transition assumptions only; not a Malaysian hazard probability model.')
