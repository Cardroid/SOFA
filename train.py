import os
from typing import Any

import torch
from torch import nn
from torch.utils.data import DataLoader
import lightning.pytorch as pl
from modules.model.forced_aligner_model import ForcedAlignmentModel
import pathlib
from dataset import MixedDataset, collate_fn
from torch.utils.data import DataLoader
import lightning as pl
import yaml
from modules.loss.GHMLoss import GHMLoss, CTCGHMLoss
from modules.loss.BinaryEMDLoss import BinaryEMDLoss
from modules.model.forced_aligner_model import ForcedAlignmentModel
import torch.nn as nn
from torch.optim.lr_scheduler import OneCycleLR
from modules.scheduler.gaussian_ramp_up_scheduler import GaussianRampUpScheduler
from torch.utils.tensorboard import SummaryWriter
from tqdm import tqdm
import torch
import click
from einops import rearrange, repeat
import math
from modules.model.lightning_model import LitForcedAlignmentModel


@click.command()
@click.option("--config_path", "-c", type=str, default="configs/config.yaml", show_default=True, help="config path")
def main(config_path: str):
    os.environ['TORCH_CUDNN_V8_API_ENABLED'] = '1'  # Prevent unacceptable slowdowns when using 16 precision
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    with open(pathlib.Path(config["global"]["binary_data_folder"]) / "vocab.yaml") as f:
        vocab_text = f.read()
    torch.set_float32_matmul_precision(config["train"]["float32_matmul_precision"])
    pl.seed_everything(config["train"]["random_seed"], workers=True)

    # define dataset
    train_dataset = MixedDataset(config["global"]["binary_data_folder"], prefix="train")
    train_dataloader = DataLoader(
        dataset=train_dataset,
        batch_size=config["train"]["batch_size"],
        shuffle=True,
        collate_fn=collate_fn,
        num_workers=config["train"]["dataloader_workers"],
    )

    valid_dataset = MixedDataset(config["global"]["binary_data_folder"], prefix="valid")
    valid_dataloader = DataLoader(
        dataset=valid_dataset,
        batch_size=config["train"]["batch_size"],
        shuffle=False,
        collate_fn=collate_fn,
        drop_last=True,
        num_workers=config["train"]["dataloader_workers"],
    )

    # model
    lightning_alignment_model = LitForcedAlignmentModel(vocab_text,
                                                        config["mel_spec"],
                                                        config["global"]["input_feature_dims"],
                                                        config["global"]["max_frame_num"],
                                                        config["train"]["learning_rate"],
                                                        config["train"]["weight_decay"],
                                                        config["train"]["hidden_dims"],
                                                        config["train"]["init_type"],
                                                        config["train"]["label_smoothing"],
                                                        )

    # trainer
    trainer = pl.Trainer(accelerator=config["train"]["accelerator"],
                         devices=config["train"]["devices"],
                         precision=config["train"]["precision"],
                         gradient_clip_val=config["train"]["gradient_clip_val"],
                         gradient_clip_algorithm=config["train"]["gradient_clip_algorithm"],
                         default_root_dir=str(pathlib.Path("ckpt") / config["global"]["model_name"]),
                         val_check_interval=config["train"]["val_check_interval"],
                         check_val_every_n_epoch=None,
                         )
    # resume training state
    ckpt_path_list = (pathlib.Path("ckpt") / config["global"]["model_name"]).rglob("*.ckpt")
    ckpt_path_list = sorted(ckpt_path_list, key=lambda x: int(x.stem.split("step=")[-1]), reverse=True)
    if len(ckpt_path_list) > 0:
        print(f"Resume training from {ckpt_path_list[0]}")

    # start training
    trainer.fit(model=lightning_alignment_model,
                train_dataloaders=train_dataloader,
                val_dataloaders=valid_dataloader,
                ckpt_path=str(ckpt_path_list[0]) if len(ckpt_path_list) > 0 else None)


if __name__ == "__main__":
    main()
