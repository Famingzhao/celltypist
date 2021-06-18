import numpy as np
import pandas as pd
import scanpy as sc
from scanpy import AnnData
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import SGDClassifier
from typing import Optional, Union
from .models import Model
from . import logger
from scipy.sparse import spmatrix
from datetime import datetime

def _to_vector(_vector_or_file):
    """
    For internal use. Turn a file into an array.
    """
    if isinstance(_vector_or_file, str):
        try:
            return pd.read_csv(_vector_or_file, header=None)[0].values
        except Exception as e:
            raise Exception(f"🛑 {e}")
    else:
        return _vector_or_file

def _to_array(_array_like) -> np.ndarray:
    """
    For internal use. Turn an array-like object into an array.
    """
    if isinstance(_array_like, pd.DataFrame):
        return _array_like.values
    elif isinstance(_array_like, spmatrix):
        return _array_like.toarray()
    elif isinstance(_array_like, np.matrix):
        return np.array(_array_like)
    elif isinstance(_array_like, np.ndarray):
        return _array_like
    else:
        raise ValueError(f"🛑 Please provide a valid array-like object as input")

def _prepare_data(X, labels, genes, transpose) -> tuple:
    """
    For internal use. Prepare data for celltypist training.
    """
    if (X is None) or (labels is None):
        raise Exception("🛑 Missing training data and/or training labels. Please provide both arguments")
    if isinstance(X, AnnData) or (isinstance(X, str) and X.endswith('.h5ad')):
        adata = sc.read(X) if isinstance(X, str) else X
        if adata.X.min() < 0:
            logger.info("👀 Detected scaled expression in the input data, will try the .raw attribute")
            try:
                indata = adata.raw.X.copy()
                genes = adata.raw.var_names.copy()
            except Exception as e:
                raise Exception(f"🛑 Fail to use the .raw attribute in the input object. {e}")
        else:
            indata = adata.X.copy()
            genes = adata.var_names.copy()
        if isinstance(labels, str) and (labels in adata.obs):
            labels = adata.obs[labels]
        else:
            labels = _to_vector(labels)
    elif isinstance(X, str) and X.endswith(('.csv', '.txt', '.tsv', '.tab', '.mtx', '.mtx.gz')):
        adata = sc.read(X)
        if transpose:
            adata = adata.transpose()
        if X.endswith(('.mtx', '.mtx.gz')):
            if genes is None:
                raise Exception("🛑 Missing `genes`. Please provide this argument together with the input mtx file")
            genes = _to_vector(genes)
            if len(genes) != adata.n_vars:
                raise ValueError(f"🛑 The number of genes provided does not match the number of genes in {X}")
            adata.var_names = np.array(genes)
        adata.var_names_make_unique()
        sc.pp.normalize_total(adata, target_sum=1e4)
        sc.pp.log1p(adata)
        indata = adata.X.copy()
        genes = adata.var_names.copy()
        labels = _to_vector(labels)
    elif isinstance(X, str):
        raise ValueError("🛑 Invalid input. Supported types: .csv, .txt, .tsv, .tab, .mtx, .mtx.gz and .h5ad")
    else:
        logger.info("👀 The input training data is processed as an array-like object")
        indata = X.copy()
        if transpose:
            indata = indata.transpose()
        if isinstance(indata, pd.DataFrame):
            genes = indata.columns.copy()
        else:
            if genes is None:
                raise Exception("🛑 Missing `genes`. Please provide this argument together with the input training data")
            genes = _to_vector(genes)
        labels = _to_vector(labels)
    return indata, labels, genes

def _SGDClassifier(indata, labels,
                   alpha, max_iter, n_jobs,
                   mini_batch, batch_number, batch_size, epochs, **kwargs) -> SGDClassifier:
    """
    For internal use. Get the SGDClassifier.
    """
    classifier = SGDClassifier(loss = 'log', alpha = alpha, max_iter = max_iter, n_jobs = n_jobs, **kwargs)
    if not mini_batch:
        logger.info(f"🏋️ Training data using SGD logistic regression")
        classifier.fit(indata, labels)
    else:
        logger.info(f"🏋️ Training data using mini-batch SGD logistic regression")
        no_cells = len(labels)
        if no_cells <= batch_size:
            raise ValueError(f"🛑 Number of cells is fewer than the batch size ({batch_size}). Decrease `batch_size`, or use SGD directly (mini_batch = False)")
        starts = np.arange(0, no_cells, batch_size)
        starts = starts[:min([batch_number, len(starts)])]
        for epoch in range(1, (epochs+1)):
            logger.info(f"⏳ Epochs: [{epoch}/{epochs}]")
            indata, labels = shuffle(indata, labels)
            for start in starts:
                classifier.partial_fit(indata[start:start+batch_size], labels[start:start+batch_size], classes = np.unique(labels))
    return classifier

def train(X = None,
          labels: Optional[Union[str, list, tuple, np.ndarray, pd.Series, pd.Index]] = None,
          genes: Optional[Union[str, list, tuple, np.ndarray, pd.Series, pd.Index]] = None,
          transpose_input: bool = False,
          #SGD param
          alpha: float = 0.0001, max_iter: int = 1000, n_jobs: Optional[int] = None,
          #mini-batch
          mini_batch: bool = False, batch_number: int = 100, batch_size: int = 1000, epochs: int = 10,
          #feature selection
          feature_selection: bool = False, top_genes: int = 500,
          #description
          date: str = '', details: str = '', url: str = '',
          #other SGD param
          **kwargs
         ) -> Model:
    """
    coming soon...
    """
    #prepare
    logger.info("🍳 Preparing data before training")
    indata, labels, genes = _prepare_data(X, labels, genes, transpose_input)
    indata = _to_array(indata)
    labels = np.array(labels)
    genes = np.array(genes)
    #check
    if np.abs(np.expm1(indata[0]).sum()-10000) > 1:
        raise ValueError("🛑 Invalid expression matrix, expect log1p normalized expression to 10000 counts per cell")
    if len(labels) != indata.shape[0]:
        raise ValueError(f"🛑 Length of training labels ({len(labels)}) does not match the number of input cells ({indata.shape[0]})")
    if len(genes) != indata.shape[1]:
        raise ValueError(f"🛑 The number of genes ({len(genes)}) provided does not match the number of genes in the training data ({indata.shape[1]})")
    #filter
    flag = indata.sum(axis = 0) == 0
    if flag.sum() > 0:
        logger.info(f"✂️ {flag.sum()} non-expressed genes are filtered out")
        indata = indata[:, ~flag]
        genes = genes[~flag]
    #scaler
    logger.info(f"⚖️ Scaling input data")
    scaler = StandardScaler()
    indata = scaler.fit_transform(indata)
    indata = np.clip(indata, a_min = None, a_max = 10)
    #classifier
    classifier = _SGDClassifier(indata = indata, labels = labels,
                                alpha = alpha, max_iter = max_iter, n_jobs = n_jobs,
                                mini_batch = mini_batch, batch_number = batch_number, batch_size = batch_size, epochs = epochs, **kwargs)
    #feature selection -> new classifier and scaler
    if feature_selection:
        logger.info(f"🔎 Selecting features")
        if len(genes) <= top_genes:
            raise ValueError(f"🛑 The number of genes ({len(genes)}) is fewer than the `top_genes` ({top_genes}). Unable to perform feature selection")
        gene_index = np.argpartition(np.abs(classifier.coef_), -top_genes, axis = 1)[:, -top_genes:]
        gene_index = np.unique(gene_index)
        logger.info(f"🧬 {len(gene_index)} features are selected")
        genes = genes[gene_index]
        indata = indata[:, gene_index]
        logger.info(f"🏋️ Starting the second round of training")
        classifier = _SGDClassifier(indata = indata, labels = labels,
                                    alpha = alpha, max_iter = max_iter, n_jobs = n_jobs,
                                    mini_batch = mini_batch, batch_number = batch_number, batch_size = batch_size, epochs = epochs, **kwargs)
        scaler.mean_ = scaler.mean_[gene_index]
        scaler.var_ = scaler.var_[gene_index]
        scaler.scale_ = scaler.scale_[gene_index]
        scaler.n_features_in_ = len(gene_index)
    #model finalization
    classifier.features = genes
    if not date:
        date = str(datetime.now())
    description = {'date': date, 'details': details, 'url': url}
    logger.info(f"✅ Model training done!")
    return Model(classifier, scaler, description)
