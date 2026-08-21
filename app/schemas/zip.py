import zipfile
import os
import tempfile
from tqdm import tqdm
from ..wrapers.logging import logging
from ..constants import Msg, SECRET_EXTENSION
from .extra import extra_compress, extra_decompress
from .container_zip import write_zip_to_cont
from ..read_operations import process_subdirs, process_subfiles, read_archive

def zip_archive(container_path: str, offset: int, files, directories, extra_dir: str, buffer_size: int, isDisk: bool) -> int:
    bytes_written = 0

    def check_archive(zipf):
        logging.info(Msg.Info.validating_archive)
        res = zipf.testzip()
        if res is None:
            logging.info(Msg.Info.archive_validated)
        else:
            logging.warning(Msg.Warn.archive_integrity_check_failed(res))

    tempfile = "temp.zip"
    try:
        with zipfile.ZipFile(tempfile, 'w', zipfile.ZIP_DEFLATED) as zipf:

            total_files = len(files) + sum(len(files)
                                           for d in directories for _, _, files in os.walk(d))

            if extra_dir != "" and os.path.isdir(extra_dir):
                total_files += 1

            with tqdm(total=total_files, desc=Msg.PBar.adding_to_archive, unit="file") as pbar:
                for file in files:
                    if file != "":
                        try:
                            zipf.write(file, os.path.basename(file))
                            logging.info(Msg.Info.file_added_to_archive(file))
                            pbar.update(1)
                        except Exception as e:
                            logging.error(
                                Msg.Err.adding_file_to_archive_error(file, e))
                            return 0

                for dir in directories:
                    if os.path.isdir(dir):
                        is_empty = True
                        for root, sub_dirs, files in os.walk(dir):
                            process_subdirs(root, sub_dirs, zipf)
                            is_empty = process_subfiles(
                                root, dir, files, zipf, pbar)
                        if is_empty:
                            arcname = os.path.relpath(
                                dir, start=os.path.dirname(dir)) + '/'
                            zipf.writestr(arcname, '')
                            logging.info(Msg.Info.added_directory(dir))

                if os.path.isdir(extra_dir):
                    archive_name = os.path.basename(extra_dir) + SECRET_EXTENSION
                    extra_compress("524m", extra_dir, archive_name, zipf)
                    pbar.update(1)



            check_archive(zipf)
    except Exception as e:
        logging.error(Msg.Err.processing_archive_error(e))
        return 0
    finally:
        bytes_written = write_zip_to_cont(container_path, tempfile, offset, buffer_size, isDisk)
        os.remove(tempfile)
        return bytes_written

def unzip_archive(container_path: str, offset: int, size: int, output_path: str, buffer_size: int, isDisk: bool) -> None:
    temp_file = None
    extra_file = ""
    try:
        temp_file = read_archive(container_path, offset, size, buffer_size, isDisk)
        with zipfile.ZipFile(temp_file.name, 'r') as zipf:
            file_list = zipf.namelist()
            with tqdm(total=len(file_list), desc=Msg.PBar.extracting_file, unit="file") as pbar:
                for file_to_extract in file_list:
                    root, extension = os.path.splitext(file_to_extract)
                    if extension == SECRET_EXTENSION:
                        zipf.extract(file_to_extract, path=".")
                        extra_file = file_to_extract
                        extra_decompress(extra_file, output_path)
                        pbar.update(1)
                        continue
                    zipf.extract(file_to_extract, path=output_path)
                    logging.info(Msg.Info.file_extracted(file_to_extract))
                    pbar.update(1)
    except Exception as e:
        logging.error(Msg.Err.processing_archive_error(e))
    finally:
        if temp_file:
            temp_file.close()
            os.remove(temp_file.name)
            if os.path.exists(extra_file):
                os.remove(extra_file)
