#!/bin/bash --login

# === SGE Directives ===
# These lines with #$ prefix are special directives for the Sun Grid Engine scheduler
#$ -cwd                       # Run the job in the current working directory
#$ -j y                       # Merge the standard error and standard output
#$ -o monotop_200A_job.log    # Name of the output log file
#$ -pe smp.pe 4               # Request 4 cores in the shared memory parallel environment 
#$ -l h_rt=24:00:00           # Request 24 hours of runtime
#$ -l mem=8G                  # Request 8GB of memory
#$ -N monotop_200A            # Name of the job

# === Environment Setup ===
# Let the system know where to find the modules
echo "Setting up environment..."
echo "Job running on node: $(hostname)"
echo "Current working directory: $(pwd)"

# Assuming poetry/conda environments are already set up as per instructions
# Load any necessary modules (adjust based on CSF availability)
# module load python/3.9.0
# module load cuda/11.0

# === Project Setup ===
# Create workspace and project directories
echo "Creating workspace and project..."
WORKSPACE="monotop_job"
PROJECT="Planar_ConvVAE_500ep"
DATA_SIGNAL="monotop_200_A"

# Create the project and set up directories
poetry run bead -m new_project -p $WORKSPACE $PROJECT

# === Configuration Customization ===
# Modify configuration file for our specific requirements
CONFIG_PATH="workspaces/$WORKSPACE/$PROJECT/config/${PROJECT}_config.py"
echo "Modifying configuration file at $CONFIG_PATH..."

# Backup original config
cp $CONFIG_PATH "${CONFIG_PATH}.bak"

# Use sed to replace configuration parameters
# Set epochs to 500 (from default 2)
sed -i 's/c.epochs\s*=\s*2/c.epochs                       = 500/' $CONFIG_PATH

# Enable intermittent model saving every 100 epochs
sed -i 's/c.intermittent_model_saving\s*=\s*False/c.intermittent_model_saving    = True/' $CONFIG_PATH
sed -i 's/c.intermittent_saving_patience\s*=\s*100/c.intermittent_saving_patience = 100/' $CONFIG_PATH

# Increase batch size for faster training (assuming resources allow)
sed -i 's/c.batch_size\s*=\s*2/c.batch_size                  = 64/' $CONFIG_PATH

# Ensure Planar_ConvVAE is the selected model (already default, but confirming)
sed -i 's/c.model_name\s*=\s*"[^"]*"/c.model_name                   = "Planar_ConvVAE"/' $CONFIG_PATH

# === Data Preparation ===
# Copy input data files to the appropriate directory
echo "Copying input data files to workspace directory..."
cp *${DATA_SIGNAL}*.csv workspaces/$WORKSPACE/data/csv/

# === Run BEAD Pipeline ===
echo "Running BEAD pipeline..."
poetry run bead -m chain -p $WORKSPACE $PROJECT -o convertcsv_prepareinputs_train_detect_plot -v

# === Job Complete ===
echo "Job completed at $(date)"
