#!/bin/bash --login

# === SGE Directives ===
#$ -cwd                              # Run the job in the current working directory
#$ -j y                              # Merge the standard error and standard output
#$ -o monotop_200A_models_job.log    # Name of the output log file
#$ -pe smp.pe 4                      # Request 4 cores in the shared memory parallel environment 
#$ -l h_rt=72:00:00                  # Request 72 hours of runtime (extended for multiple models)
#$ -l mem=8G                         # Request 8GB of memory
#$ -N monotop_200A_models            # Name of the job

# === Environment Setup ===
echo "Setting up environment..."
echo "Job running on node: $(hostname)"
echo "Current working directory: $(pwd)"

# === Project Setup ===
# Define workspace name and data signal
WORKSPACE="monotop_all_models"
DATA_SIGNAL="monotop_200_A"

# Define an array of all NormFlow+ConvVAE model variants
MODELS=("Planar_ConvVAE" "OrthogonalSylvester_ConvVAE" "HouseholderSylvester_ConvVAE" 
        "TriangularSylvester_ConvVAE" "IAF_ConvVAE" "ConvFlow_ConvVAE" "NSFAR_ConvVAE")

# === Data Preparation (Only once for all models) ===
echo "Creating workspace and preparing data..."

# Create the base workspace
mkdir -p workspaces/$WORKSPACE/data/csv

# Copy input data files to the workspace
cp *${DATA_SIGNAL}*.csv workspaces/$WORKSPACE/data/csv/

# Create first project for data conversion and preparation
FIRST_PROJECT="${MODELS[0]}_500ep"
poetry run bead -m new_project -p $WORKSPACE $FIRST_PROJECT

# Configure first project
CONFIG_PATH="workspaces/$WORKSPACE/$FIRST_PROJECT/config/${FIRST_PROJECT}_config.py"
echo "Configuring $FIRST_PROJECT at $CONFIG_PATH..."

# Set common configurations
sed -i 's/c.epochs\s*=\s*2/c.epochs                       = 500/' $CONFIG_PATH
sed -i 's/c.intermittent_model_saving\s*=\s*False/c.intermittent_model_saving    = True/' $CONFIG_PATH
sed -i 's/c.intermittent_saving_patience\s*=\s*100/c.intermittent_saving_patience = 100/' $CONFIG_PATH
sed -i 's/c.batch_size\s*=\s*2/c.batch_size                  = 64/' $CONFIG_PATH

# Run data conversion and preparation only once
echo "Converting CSV and preparing inputs (done only once for all models)..."
poetry run bead -m chain -p $WORKSPACE $FIRST_PROJECT -o convertcsv_prepareinputs -v

# === Loop through all models and run training, detection, and plotting ===
for MODEL in "${MODELS[@]}"; do
    PROJECT="${MODEL}_500ep"
    echo "===========================================" 
    echo "Processing model: $MODEL"
    echo "===========================================" 
    
    # Skip data preparation for the first model as it's already done
    if [ "$PROJECT" != "$FIRST_PROJECT" ]; then
        echo "Creating project for $MODEL..."
        poetry run bead -m new_project -p $WORKSPACE $PROJECT
        
        # Configure this model's project
        CONFIG_PATH="workspaces/$WORKSPACE/$PROJECT/config/${PROJECT}_config.py"
        echo "Configuring $PROJECT at $CONFIG_PATH..."
        
        # Set common configurations
        sed -i 's/c.epochs\s*=\s*2/c.epochs                       = 500/' $CONFIG_PATH
        sed -i 's/c.intermittent_model_saving\s*=\s*False/c.intermittent_model_saving    = True/' $CONFIG_PATH
        sed -i 's/c.intermittent_saving_patience\s*=\s*100/c.intermittent_saving_patience = 100/' $CONFIG_PATH
        sed -i 's/c.batch_size\s*=\s*2/c.batch_size                  = 64/' $CONFIG_PATH
    fi
    
    # Set this specific model
    sed -i "s/c.model_name\s*=\s*\"[^\"]*\"/c.model_name                   = \"$MODEL\"/" $CONFIG_PATH
    
    # Run training, detection and plotting for this model
    echo "Running training, detection and plotting for $MODEL..."
    poetry run bead -m chain -p $WORKSPACE $PROJECT -o train_detect_plot -v
    
    echo "Completed processing for $MODEL"
done

# === Generate a summary of all models ===
echo "Creating summary of all model runs..."
SUMMARY_DIR="workspaces/$WORKSPACE/summary"
mkdir -p $SUMMARY_DIR

# Copy all model plots to a single directory for easy comparison
for MODEL in "${MODELS[@]}"; do
    PROJECT="${MODEL}_500ep"
    cp -r workspaces/$WORKSPACE/$PROJECT/output/plots $SUMMARY_DIR/$MODEL
done

# Create a simple HTML summary page for easy browsing
cat > $SUMMARY_DIR/index.html << EOL
<!DOCTYPE html>
<html>
<head>
    <title>BEAD Models Comparison - monotop_200_A</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        h1 { color: #333; }
        .model-section { margin-bottom: 30px; border-bottom: 1px solid #ccc; padding-bottom: 20px; }
    </style>
</head>
<body>
    <h1>BEAD Model Comparison Results - monotop_200_A</h1>
    <p>Comparison of different NormFlow+ConvVAE model combinations:</p>
EOL

for MODEL in "${MODELS[@]}"; do
    echo "    <div class='model-section'><h2>${MODEL}</h2><p>See plots in: $SUMMARY_DIR/${MODEL}</p></div>" >> $SUMMARY_DIR/index.html
done

echo "</body></html>" >> $SUMMARY_DIR/index.html

echo "Job completed at $(date)"