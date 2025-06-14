"""
Visualization utilities for model results.

This module provides functions for creating visualizations of model training results,
latent space embeddings, and performance metrics. These plots are essential for
understanding model behavior and evaluating anomaly detection performance.

Functions:
    plot_losses: Generate plots for training and validation losses.
    reduce_dim_subsampled: Reduce dimensionality with optional subsampling.
    plot_latent_variables: Visualize latent space embeddings.
    plot_mu_logvar: Plot latent space mean and variance.
    plot_roc_curve: Generate ROC curves from model results.
"""

import os

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import trimap
from sklearn.decomposition import PCA
from sklearn.manifold import TSNE
from sklearn.metrics import auc, roc_curve


def plot_losses(output_dir, save_dir, config, verbose: bool = False):
    """
    Generate plots for training and validation losses over epochs.

    This function creates two types of visualizations:
    1. Training and validation total loss curves per epoch
    2. Component-wise loss curves (reconstruction, KL divergence, etc.) for train/val/test sets

    Parameters
    ----------
    output_dir : str
        Directory containing the saved model output files (.npy)
    save_dir : str
        Directory where the generated plots will be saved
    config : object
        Configuration object containing model parameters like project_name and epochs
    verbose : bool, optional
        Whether to print progress messages, default is False

    Raises
    ------
    FileNotFoundError
        If required loss data files are not found in the output directory
    """
    if verbose:
        print("Making Loss Plots...")
    # --------- Plot Train & Validation Epoch Losses ---------
    train_loss_file = os.path.join(output_dir, "train_epoch_loss_data.npy")
    val_loss_file = os.path.join(output_dir, "val_epoch_loss_data.npy")

    if os.path.exists(train_loss_file) and os.path.exists(val_loss_file):
        # Load epoch-wise loss arrays (assumed 1D arrays with one value per epoch)
        train_epoch_loss = np.load(train_loss_file)
        val_epoch_loss = np.load(val_loss_file)

        epochs = np.arange(1, len(train_epoch_loss) + 1)

        plt.figure(figsize=(8, 6))
        plt.plot(epochs, train_epoch_loss, label="Train Loss", marker="o")
        plt.plot(epochs, val_epoch_loss, label="Validation Loss", marker="o")
        plt.xlabel("Epoch")
        plt.ylabel("Loss")
        plt.title(config.project_name)
        plt.legend()
        plt.tight_layout()

        # Save plot as PDF
        plt.savefig(os.path.join(save_dir, "train_metrics.pdf"))
        plt.close()
    else:
        raise FileNotFoundError(
            "Epoch loss data files not found. Make sure to run the train mode first."
        )

    # --------- Plot Loss Components ---------
    # Define the prefixes and categories of interest
    prefixes = ["loss", "reco", "kl", "emd", "l1", "l2"]
    categories = ["train", "val", "test"]

    # Iterate over each category
    for cat in categories:
        files_for_cat = []
        # For each prefix, build the file path and check if it exists.
        for prefix in prefixes:
            file_path = os.path.join(output_dir, f"{prefix}_{cat}.npy")
            if os.path.exists(file_path):
                files_for_cat.append(file_path)

        # If any files are found for the current category, process and plot them.
        if files_for_cat:
            plt.figure(figsize=(8, 6))

            for file in files_for_cat:
                data = np.load(file)
                num_epochs = config.epochs
                total_length = len(data)

                # Determine the number of events per epoch.
                # Assumes that total_length divides evenly by config.epochs.
                events_per_epoch = total_length // num_epochs

                avg_losses = []
                for epoch in range(num_epochs):
                    start_idx = epoch * events_per_epoch
                    end_idx = start_idx + events_per_epoch
                    epoch_data = data[start_idx:end_idx]
                    avg_losses.append(np.mean(epoch_data))
                avg_losses = np.array(avg_losses)

                epochs = np.arange(1, num_epochs + 1)
                # Use the file prefix (without the _category.npy) as the label.
                base_name = os.path.basename(file)
                label = os.path.splitext(base_name)[0]

                plt.plot(epochs, avg_losses, label=label, marker="o")

            plt.xlabel("Epoch")
            plt.ylabel("Average Loss")
            plt.title(config.project_name)
            plt.legend()
            plt.tight_layout()

            # Save the plot to a file with category in its name.
            save_filename = os.path.join(save_dir, f"loss_components_{cat}.pdf")
            plt.savefig(save_filename)
            plt.close()

        else:
            print(
                f"No loss component data files found for {cat} set. Make sure to run the appropriate {cat} mode first."
            )

    if verbose:
        print("Loss plots generated successfully and saved to: ", save_dir)


def reduce_dim_subsampled(
    data, method="trimap", n_components=2, n_samples=None, verbose=False
):
    """
    Reduce dimensionality of data with optional subsampling for large datasets.

    This function applies dimensionality reduction techniques (PCA, t-SNE, or TriMap)
    to high-dimensional data, with options for subsampling large datasets to improve
    computational efficiency.

    Parameters
    ----------
    data : numpy.ndarray
        Input data of shape (n_samples, n_features)
    method : str, optional
        Dimensionality reduction method to use: "pca", "tsne", or "trimap", default is "trimap"
    n_components : int, optional
        Number of dimensions to reduce to, default is 2
    n_samples : int, optional
        Number of samples to use (subsampling), if None uses all data, default is None
    verbose : bool, optional
        Whether to print progress messages, default is False

    Returns
    -------
    numpy.ndarray
        Reduced data with shape (n_samples, n_components)
    str
        The name of the dimensionality reduction method used
    numpy.ndarray
        Indices of the samples used for subsampling

    Raises
    ------
    ValueError
        If an invalid dimensionality reduction method is specified
    """
    # Subsampling for large datasets
    if n_samples is not None and data.shape[0] > n_samples:
        if verbose:
            print(f"Subsampling {data.shape[0]} points to {n_samples} points...")
        indices = np.random.choice(data.shape[0], n_samples, replace=False)
        data = data[indices]
    else:
        indices = np.arange(data.shape[0])  # Use all data

    # PCA preprocessing for high-dimensional data
    if data.shape[1] > 50:
        if verbose:
            print(f"Applying PCA to reduce from {data.shape[1]} to 50 dimensions...")
        data = PCA(n_components=50).fit_transform(data)

    # Apply the selected dimensionality reduction method
    method = method.lower()
    if method == "pca":
        if verbose:
            print("Reducing to 2 dimensions using PCA...")
        reducer = PCA(n_components=n_components)
        reduced = reducer.fit_transform(data)
        method_used = "pca"
    elif method == "tsne":
        if verbose:
            print("Reducing to 2 dimensions using t-SNE...")
        reducer = TSNE(n_components=n_components, random_state=42)
        reduced = reducer.fit_transform(data)
        method_used = "t-sne"
    elif method == "trimap":
        if verbose:
            print("Reducing to 2 dimensions using TriMap...")
        reducer = trimap.TRIMAP(n_dims=n_components)
        reduced = reducer.fit_transform(data)
        method_used = "trimap"
    else:
        raise ValueError(
            f"Invalid method: {method}. Must be 'pca', 'tsne', or 'trimap'."
        )

    return reduced, method_used, indices


def plot_latent_variables(config, paths, verbose=False):
    """
    Visualize latent space embeddings from the model.

    This function creates 2D projections of the latent space using dimensionality
    reduction techniques (PCA, t-SNE, or TriMap) for both initial (z0) and final (zk)
    latent variables, color-coded by class.

    Parameters
    ----------
    config : object
        Configuration object containing parameters like latent_space_size,
        latent_space_plot_style, input_level, etc.
    paths : dict
        Dictionary of paths including output_path and data_path
    verbose : bool, optional
        Whether to print progress and debugging information, default is False

    Notes
    -----
    The function handles both training and test data, with different color
    schemes for each. For test data, signal samples are shown in red, while
    background samples are colored according to their generator type.
    """
    prefixes = ["train_", "test_"]

    def reduce_dim(data):
        if config.latent_space_size > 50:
            if verbose:
                print(
                    f"Applying PCA to reduce latent space from {config.latent_space_size} to 50 dimensions..."
                )
            data = PCA(n_components=50).fit_transform(data)

        style = config.latent_space_plot_style.lower()
        if style == "pca":
            reducer = PCA(n_components=2)
            method = "pca"
        elif style == "tsne":
            reducer = TSNE(n_components=2, random_state=42)
            method = "t-sne"
        elif style == "trimap":
            reducer = trimap.TRIMAP(n_dims=2)
            method = "trimap"
        else:
            raise ValueError(
                f"Invalid latent_space_plot_style: {style}. Must be 'pca', 'tsne', or 'trimap'."
            )

        if verbose:
            print(f"Reducing to 2 dimensions using {method.upper()}...")
        return reducer.fit_transform(data), method

    for prefix in prefixes:
        # Construct file paths
        label_path = os.path.join(
            paths["output_path"], "results", f"{prefix}{config.input_level}_label.npy"
        )
        gen_label_path = os.path.join(
            paths["data_path"],
            config.file_type,
            "tensors",
            "processed",
            f"{prefix}gen_label_{config.input_level}.npy",
        )
        z0_path = os.path.join(paths["output_path"], "results", f"{prefix}z0_data.npy")
        zk_path = os.path.join(paths["output_path"], "results", f"{prefix}zk_data.npy")

        # Check if required files exist
        required_files = [gen_label_path, z0_path, zk_path]
        if prefix == "test_":
            required_files.append(label_path)  # Only test prefix requires label file

        if not all(os.path.exists(f) for f in required_files):
            if verbose:
                print(f"Skipping {prefix} due to missing files")
            continue

        try:
            gen_labels = np.load(gen_label_path)
            z0 = np.load(z0_path)
            zk = np.load(zk_path)
            labels = np.load(label_path) if prefix == "test_" else None

            # Determine minimum length among relevant arrays
            if prefix == "train_":
                min_length = min(len(gen_labels), len(z0), len(zk))
            else:
                min_length = min(len(gen_labels), len(z0), len(zk), len(labels))

            # Clip arrays to min_length
            gen_labels = gen_labels[:min_length]
            z0 = z0[:min_length]
            zk = zk[:min_length]
            if prefix == "test_":
                labels = labels[:min_length]

            if prefix == "test_":
                n_background = np.sum(labels == 0)
                if len(gen_labels) != n_background:
                    print(f"Skipping {prefix}: gen_label/label mismatch after clipping")
                    continue

        except Exception as e:
            if verbose:
                print(f"Error loading {prefix} files: {e}")
            continue

        # Define colors based on prefix
        if prefix == "train_":
            # Only Herwig, Pythia, and Sherpa classes for train prefix
            colors = []
            for i in range(len(gen_labels)):
                if gen_labels[i] == 0:
                    colors.append("green")
                elif gen_labels[i] == 1:
                    colors.append("blue")
                elif gen_labels[i] == 2:
                    colors.append("yellow")
                else:
                    colors.append("black")  # Fallback for unexpected labels
        else:
            # For test prefix, include signal (red) and background classes
            colors = []
            for i in range(n_background):
                if gen_labels[i] == 0:
                    colors.append("green")
                elif gen_labels[i] == 1:
                    colors.append("blue")
                elif gen_labels[i] == 2:
                    colors.append("yellow")
                else:
                    colors.append("black")
            colors.extend(["red"] * (len(labels) - n_background))

        # Plot latent variables
        for data, latent_suffix in [(z0, "_z0"), (zk, "_zk")]:
            if config.subsample_plot:
                colors_z = []
                reduced, method, indices = reduce_dim_subsampled(
                    data,
                    method=config.latent_space_plot_style,
                    n_samples=config.subsample_size,
                    verbose=verbose,
                )
                colors_z = [colors[i] for i in indices]
            else:
                reduced, method = reduce_dim(data)
                colors_z = colors
            plt.figure(figsize=(8, 6))
            plt.scatter(
                reduced[:, 0],
                reduced[:, 1],
                c=colors_z,
                alpha=0.7,
                edgecolors="w",
                s=60,
            )
            plt.title(
                f"{latent_suffix[1:].upper()} {method.upper()} Embedding ({prefix[:-1]})"
            )
            plt.xlabel("Component 1")
            plt.ylabel("Component 2")

            # Create legend based on prefix
            if prefix == "train_":
                legend = [
                    mpatches.Patch(color="green", label="Herwig"),
                    mpatches.Patch(color="blue", label="Pythia"),
                    mpatches.Patch(color="yellow", label="Sherpa"),
                ]
            else:
                legend = [
                    mpatches.Patch(color="green", label="Herwig"),
                    mpatches.Patch(color="blue", label="Pythia"),
                    mpatches.Patch(color="yellow", label="Sherpa"),
                    mpatches.Patch(color="red", label="Signal"),
                ]
            plt.legend(handles=legend)

            save_path = os.path.join(
                paths["output_path"],
                "plots",
                "latent_space",
                f"{prefix[:-1]}{latent_suffix}.pdf",
            )
            plt.savefig(save_path, format="pdf")
            plt.close()


def plot_mu_logvar(config, paths, verbose=False):
    """
    Visualize the mean (mu) and log-variance (logvar) of the latent space distribution.

    This function creates two types of visualizations:
    1. 2D projection of the mean vectors in latent space, color-coded by class
    2. Histogram of uncertainties derived from the log-variance

    Parameters
    ----------
    config : object
        Configuration object containing parameters like latent_space_size,
        latent_space_plot_style, input_level, etc.
    paths : dict
        Dictionary of paths including output_path and data_path
    verbose : bool, optional
        Whether to print progress and debugging information, default is False

    Notes
    -----
    The uncertainty is calculated as the mean of the standard deviation (sigma)
    across all dimensions of the latent space, where sigma = exp(0.5 * logvar).
    """
    prefixes = ["train_", "test_"]

    def reduce_dim(data):
        if config.latent_space_size > 50:
            data = PCA(n_components=50).fit_transform(data)
        style = config.latent_space_plot_style.lower()
        if style == "pca":
            return PCA(n_components=2).fit_transform(data), "pca"
        elif style == "tsne":
            return TSNE(n_components=2, random_state=42).fit_transform(data), "t-sne"
        elif style == "trimap":
            return trimap.TRIMAP(n_dims=2).fit_transform(data), "trimap"
        else:
            raise ValueError("Invalid reduction method")

    for prefix in prefixes:
        mu_path = os.path.join(paths["output_path"], "results", f"{prefix}mu_data.npy")
        logvar_path = os.path.join(
            paths["output_path"], "results", f"{prefix}logvar_data.npy"
        )
        label_path = os.path.join(
            paths["output_path"], "results", f"{prefix}{config.input_level}_label.npy"
        )
        gen_label_path = os.path.join(
            paths["data_path"],
            config.file_type,
            "tensors",
            "processed",
            f"{prefix}gen_label_{config.input_level}.npy",
        )

        # Check if required files exist
        required_files = [mu_path, logvar_path, gen_label_path]
        if prefix == "test_":
            required_files.append(label_path)  # Only test prefix requires label file

        if not all(os.path.exists(f) for f in required_files):
            if verbose:
                print(f"Skipping {prefix} due to missing files")
            continue

        try:
            mu = np.load(mu_path)
            logvar = np.load(logvar_path)
            gen_labels = np.load(gen_label_path)
            labels = np.load(label_path) if prefix == "test_" else None

            # Determine minimum length among relevant arrays
            if prefix == "train_":
                min_length = min(len(gen_labels), len(mu), len(logvar))
            else:
                min_length = min(len(gen_labels), len(mu), len(logvar), len(labels))

            # Clip arrays to min_length
            gen_labels = gen_labels[:min_length]
            mu = mu[:min_length]
            logvar = logvar[:min_length]
            if prefix == "test_":
                labels = labels[:min_length]

            if prefix == "test_":
                n_background = np.sum(labels == 0)
                if len(gen_labels) != n_background:
                    print(f"Skipping {prefix}: gen_label/label mismatch after clipping")
                    continue

        except Exception as e:
            if verbose:
                print(f"Error loading {prefix} files: {e}")
            continue

        # Define colors based on prefix
        if prefix == "train_":
            # Only Herwig, Pythia, and Sherpa classes for train prefix
            colors = []
            for i in range(len(gen_labels)):
                if gen_labels[i] == 0:
                    colors.append("green")
                elif gen_labels[i] == 1:
                    colors.append("blue")
                elif gen_labels[i] == 2:
                    colors.append("yellow")
                else:
                    colors.append("black")
        else:
            # For test prefix, include signal (red) and background classes
            colors = []
            for i in range(n_background):
                if gen_labels[i] == 0:
                    colors.append("green")
                elif gen_labels[i] == 1:
                    colors.append("blue")
                elif gen_labels[i] == 2:
                    colors.append("yellow")
                else:
                    colors.append("black")
            colors.extend(["red"] * (len(labels) - n_background))

        # Plot latent means (mu)
        if config.subsample_plot:
            colors_z = []
            reduced_mu, method, indices = reduce_dim_subsampled(
                mu,
                method=config.latent_space_plot_style,
                n_samples=config.subsample_size,
                verbose=verbose,
            )
            colors_z = [colors[i] for i in indices]
        else:
            reduced_mu, method = reduce_dim(mu)
            colors_z = colors
        plt.figure(figsize=(8, 6))
        plt.scatter(
            reduced_mu[:, 0],
            reduced_mu[:, 1],
            c=colors_z,
            alpha=0.7,
            edgecolors="w",
            s=60,
        )
        plt.title(f"Mu {method.upper()} Embedding ({prefix[:-1]})")
        # Create legend based on prefix
        if prefix == "train_":
            legend = [
                mpatches.Patch(color="green", label="Herwig"),
                mpatches.Patch(color="blue", label="Pythia"),
                mpatches.Patch(color="yellow", label="Sherpa"),
            ]
        else:
            legend = [
                mpatches.Patch(color="green", label="Herwig"),
                mpatches.Patch(color="blue", label="Pythia"),
                mpatches.Patch(color="yellow", label="Sherpa"),
                mpatches.Patch(color="red", label="Signal"),
            ]
        plt.legend(handles=legend)
        plt.savefig(
            os.path.join(
                paths["output_path"],
                "plots",
                "latent_space",
                f"{config.project_name}_{prefix[:-1]}_mu.pdf",
            )
        )
        plt.close()

        # Plot uncertainty
        sigma = np.exp(0.5 * logvar)
        uncertainty = np.mean(sigma, axis=1)
        plt.figure(figsize=(8, 6))
        for color, values in zip(
            ["green", "blue", "yellow", "red"],
            [
                uncertainty[gen_labels == 0],
                uncertainty[gen_labels == 1],
                uncertainty[gen_labels == 2],
                uncertainty[len(gen_labels) :] if prefix == "test_" else [],
            ],
            strict=False,
        ):
            if len(values) > 0:
                plt.hist(values, bins=30, alpha=0.6, color=color)
        plt.title(f"Uncertainty Distribution ({prefix[:-1]})")
        plt.savefig(
            os.path.join(
                paths["output_path"],
                "plots",
                "latent_space",
                f"{prefix[:-1]}_uncertainty.pdf",
            )
        )
        plt.close()


def plot_roc_curve(config, paths, verbose: bool = False):
    """
    Generate and save ROC curves for available loss component files.

    This function computes and plots Receiver Operating Characteristic (ROC) curves
    for different loss components, evaluating their effectiveness as anomaly scores.

    Parameters
    ----------
    config : object
        Configuration object containing parameters like input_level and project_name
    paths : dict
        Dictionary containing paths, particularly output_path
    verbose : bool, optional
        Whether to print additional debug information, default is False

    Raises
    ------
    FileNotFoundError
        If the required label file is not found
    ValueError
        If ground truth labels are not a 1D array or if there's a length mismatch
        between loss scores and ground truth labels

    Notes
    -----
    The function generates a single plot containing ROC curves for all available
    loss components (total loss, reconstruction loss, KL divergence, etc.),
    with the area under the curve (AUC) displayed in the legend.
    """
    # Load ground truth binary labels from 'label.npy'
    label_path = os.path.join(
        paths["output_path"], "results", "test_" + config.input_level + "_label.npy"
    )
    output_dir = os.path.join(paths["output_path"], "results")
    # check if the label file exists
    if not os.path.exists(label_path):
        raise FileNotFoundError(f"Label file not found: {label_path}")
    else:
        ground_truth = np.load(label_path)

    # Ensure ground_truth is a 1D array
    if ground_truth.ndim != 1:
        raise ValueError("Ground truth labels must be a 1D array.")

    # Define the loss component prefixes to search for.
    loss_components = ["loss", "reco", "kl", "emd", "l1", "l2"]

    # Iterate over each loss component and generate ROC curve.
    plt.figure(figsize=(8, 6))

    for component in loss_components:
        file_path = os.path.join(output_dir, f"{component}_test.npy")

        if not os.path.exists(file_path):
            continue  # Skip if the file does not exist

        # Load loss scores
        data = np.load(file_path)

        # Ensure that data is a 1D array (flatten if necessary).
        if data.ndim > 1:
            data = data.flatten()

        # Check if the length of data matches the length of ground_truth
        if len(data) != len(ground_truth):
            raise ValueError(
                f"Length mismatch: {file_path} has {len(data)} entries; "
                f"ground truth has {len(ground_truth)} entries."
            )

        # Compute ROC curve and AUC.
        fpr, tpr, thresholds = roc_curve(ground_truth, data)
        roc_auc = auc(fpr, tpr)

        # Plot the ROC curve.
        plt.plot(fpr, tpr, label=f"{component.capitalize()}) AUC = {roc_auc:.2f}", lw=2)

    plt.plot([0, 1], [0, 1], "k--", lw=2, label="Random Guess")
    plt.xlabel("False Positive Rate")
    plt.ylabel("True Positive Rate")
    plt.title(f"ROC Curve - {config.project_name}")
    plt.legend(loc="lower right")
    plt.tight_layout()

    # Save the plot as a PDF file.
    save_filename = os.path.join(paths["output_path"], "plots", "loss", "roc.pdf")
    plt.savefig(save_filename)
    plt.close()
