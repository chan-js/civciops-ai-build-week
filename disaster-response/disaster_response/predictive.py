"""Small transparent synthetic logistic baseline with chronological holdout."""
import numpy as np
from scipy.optimize import minimize
from scipy.special import expit


def train_demo(seed=17):
    rng = np.random.default_rng(seed)
    n = 480
    rain = np.zeros(n)
    river = np.zeros(n)
    for t in range(1,n):
        rain[t] = max(0, .62*rain[t-1]+rng.gamma(1.4,12)-8)
        river[t] = max(0, .86*river[t-1]+.012*rain[t]+rng.normal(0,.12))
    # Only t-1 observations predict an event at t. Not real measurements.
    X = np.column_stack([rain[:-1],river[:-1]])
    y = rng.binomial(1, expit(-3+.035*X[:,0]+1.2*X[:,1]))
    split = 335
    mean, std = X[:split].mean(0), X[:split].std(0)
    Z = np.column_stack([np.ones(len(X)),(X-mean)/std])
    def loss(w):
        v = Z[:split]@w
        return float(np.logaddexp(0,v).sum()-y[:split]@v+.5*np.sum(w[1:]**2))
    def grad(w):
        return Z[:split].T@(expit(Z[:split]@w)-y[:split])+np.r_[0,w[1:]]
    result = minimize(loss, np.zeros(3), jac=grad, method="BFGS")
    if not result.success:
        raise RuntimeError("Synthetic baseline did not converge: "+result.message)
    p = expit(Z[split:]@result.x)
    baseline = np.full_like(p, y[:split].mean(), dtype=float)
    return {"mode":"synthetic_training_only", "seed":seed, "features":["lag1_rain_mm","lag1_river_index"],
            "split":"first 335 observations training, remaining 144 chronological holdout; scaler fit on training only",
            "train_n":split,"test_n":len(p),"coefficients":result.x.tolist(),
            "train_mean":mean.tolist(),"train_std":std.tolist(),
            "holdout_brier":float(np.mean((p-y[split:])**2)),
            "constant_baseline_brier":float(np.mean((baseline-y[split:])**2)),
            "limitation":"Illustrates APROM/PA workflow; no predictive validity for real Malaysian floods. Not used by routing."}
