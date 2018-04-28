import csv

from .imports import *
from .torch_imports import *
from .core import *
from .transforms import *
from .layer_optimizer import *
from .dataloader import DataLoader


def get_cv_idxs(n, cv_idx=0, val_pct=0.2, seed=42):
    """ Get a list of index values for Validation set from a dataset
    
    Arguments:
        n : int, Total number of elements in the data set.
        cv_idx : int, starting index [idx_start = cv_idx*int(val_pct*n)] 
        val_pct : (int, float), validation set percentage 
        seed : seed value for RandomState
        
    Returns:
        list of indexes 
    """
    np.random.seed(seed)
    n_val = int(val_pct * n)
    idx_start = cv_idx * n_val
    idxs = np.random.permutation(n)
    return idxs[idx_start:idx_start + n_val]


def resize_img(fname, targ, path, new_path):
    """
    Enlarge or shrink a single image to scale, such that the smaller of the height or width dimension is equal to targ.
    """
    dest = os.path.join(path, new_path, str(targ), fname)
    if os.path.exists(dest):
        return
    im = Image.open(os.path.join(path, fname)).convert("RGB")
    r, c = im.size
    ratio = targ / min(r, c)
    image_size = (scale_to(r, ratio, targ), scale_to(c, ratio, targ))
    os.makedirs(os.path.split(dest)[0], exist_ok=True)
    im.resize(image_size, Image.LINEAR).save(dest)


def resize_imgs(fnames, targ, path, new_path):
    """
    Enlarge or shrink a set of images in the same directory to scale, such that the smaller of the height or width dimension is equal to targ.
    Note: 
    -- This function is multithreaded for efficiency. 
    -- When destination file or folder already exist, function exists without raising an error. 
    """
    if not os.path.exists(os.path.join(path, new_path, str(targ), fnames[0])):
        with ThreadPoolExecutor(8) as e:
            ims = e.map(lambda x: resize_img(x, targ, path, new_path), fnames)
            for x in tqdm(ims, total=len(fnames), leave=False):
                pass
    return os.path.join(path, new_path, str(targ))


def read_dir(path, folder):
    full_path = os.path.join(path, folder)
    fnames = glob(f"{full_path}/*.*")
    if any(fnames):
        return [os.path.relpath(f, path) for f in fnames]
    else:
        raise FileNotFoundError(
            "{} folder doesn't exist or is empty".format(folder)
        )


def read_dirs(path, folder):
    """
    Fetches name of all files in path in long form, and labels associated by extrapolation of directory names. 
    """
    labels, filenames, all_labels = [], [], []
    full_path = os.path.join(path, folder)
    for label in sorted(os.listdir(full_path)):
        if label not in (".ipynb_checkpoints", ".DS_Store"):
            all_labels.append(label)
            for fname in os.listdir(os.path.join(full_path, label)):
                filenames.append(os.path.join(folder, label, fname))
                labels.append(label)
    return filenames, labels, all_labels


def n_hot(ids, c):
    """
    one hot encoding by index. Returns array of length c, where all entries are 0, except for the indecies in ids
    """
    res = np.zeros((c,), dtype=np.float32)
    res[ids] = 1
    return res


def folder_source(path, folder):
    fnames, lbls, all_labels = read_dirs(path, folder)
    label2idx = {v: k for k, v in enumerate(all_labels)}
    idxs = [label2idx[lbl] for lbl in lbls]
    c = len(all_labels)
    label_arr = np.array(idxs, dtype=int)
    return fnames, label_arr, all_labels


def parse_csv_labels(fn, skip_header=True, cat_separator=" "):
    """Parse filenames and label sets from a CSV file.

    This method expects that the csv file at path :fn: has two columns. If it
    has a header, :skip_header: should be set to True. The labels in the
    label set are expected to be space separated.

    Arguments:
        fn: Path to a CSV file.
        skip_header: A boolean flag indicating whether to skip the header.

    Returns:
        a four-tuple of (
            sorted image filenames,
            a dictionary of filenames and corresponding labels,
            a sorted set of unique labels,
            a dictionary of labels to their corresponding index, which will
            be one-hot encoded.
        )
    .
    :param cat_separator: the separator for the categories column
    """
    df = pd.read_csv(
        fn, index_col=0, header=0 if skip_header else None, dtype=str
    )
    fnames = df.index.values
    df.iloc[:, 0] = df.iloc[:, 0].str.split(cat_separator)
    return sorted(fnames), list(df.to_dict().values())[0]


def nhot_labels(label2idx, csv_labels, fnames, c):

    all_idx = {
        k: n_hot([label2idx[o] for o in v], c) for k, v in csv_labels.items()
    }
    return np.stack([all_idx[o] for o in fnames])


def csv_source(
    folder, csv_file, skip_header=True, suffix="", continuous=False
):
    fnames, csv_labels = parse_csv_labels(csv_file, skip_header)
    return dict_source(folder, fnames, csv_labels, suffix, continuous)


def dict_source(folder, fnames, csv_labels, suffix="", continuous=False):
    all_labels = sorted(list(set(p for o in csv_labels.values() for p in o)))
    full_names = [os.path.join(folder, str(fn) + suffix) for fn in fnames]
    if continuous:
        label_arr = np.array(
            [np.array(csv_labels[i]).astype(np.float32) for i in fnames]
        )
    else:
        label2idx = {v: k for k, v in enumerate(all_labels)}
        label_arr = nhot_labels(label2idx, csv_labels, fnames, len(all_labels))
        is_single = np.all(label_arr.sum(axis=1) == 1)
        if is_single:
            label_arr = np.argmax(label_arr, axis=1)
    return full_names, label_arr, all_labels


class BaseDataset(Dataset):
    """An abatch_sizetract class representing a fastai dataset, it extends torch.utils.data.Dataset."""

    def __init__(self, transform=None):
        self.transform = transform
        self.n = self.get_n()
        self.c = self.get_c()
        self.image_size = self.get_image_size()

    def get1item(self, idx):
        x, y = self.get_x(idx), self.get_y(idx)
        return self.get(self.transform, x, y)

    def __getitem__(self, idx):
        if isinstance(idx, slice):
            xs, ys = zip(
                *[self.get1item(i) for i in range(*idx.indices(self.n))]
            )
            return np.stack(xs), ys
        return self.get1item(idx)

    def __len__(self):
        return self.n

    def get(self, tfm, x, y):
        return (x, y) if tfm is None else tfm(x, y)

    @abstractmethod
    def get_n(self):
        """Return number of elements in the dataset == len(self)."""
        raise NotImplementedError

    @abstractmethod
    def get_c(self):
        """Return number of classes in a dataset."""
        raise NotImplementedError

    @abstractmethod
    def get_image_size(self):
        """Return maximum size of an image in a dataset."""
        raise NotImplementedError

    @abstractmethod
    def get_x(self, i):
        """Return i-th example (image, wav, etc)."""
        raise NotImplementedError

    @abstractmethod
    def get_y(self, i):
        """Return i-th label."""
        raise NotImplementedError

    @property
    def is_multi(self):
        """Returns true if this data set contains multiple labels per sample."""
        return False

    @property
    def is_reg(self):
        """True if the data set is used to train regression models."""
        return False


def open_image(fn):
    """ Opens an image using OpenCV given the file path.

    Arguments:
        fn: the file path of the image

    Returns:
        The image in RGB format as numpy array of floats normalized to range between 0.0 - 1.0
    """
    flags = cv2.IMREAD_UNCHANGED + cv2.IMREAD_ANYDEPTH + cv2.IMREAD_ANYCOLOR
    if not os.path.exists(fn):
        raise OSError("No such file or directory: {}".format(fn))
    elif os.path.isdir(fn):
        raise OSError("Is a directory: {}".format(fn))
    else:
        # res = np.array(Image.open(fn), dtype=np.float32)/255
        # if len(res.shape)==2: res = np.repeat(res[...,None],3,2)
        # return res
        try:
            im = cv2.imread(str(fn), flags).astype(np.float32) / 255
            if im is None:
                raise OSError(f"File not recognized by opencv: {fn}")
            return cv2.cvtColor(im, cv2.COLOR_BGR2RGB)
        except Exception as e:
            raise OSError("Error handling image at: {}".format(fn)) from e


class FilesDataset(BaseDataset):

    def __init__(self, fnames, transform, path):
        self.path, self.fnames = path, fnames
        super().__init__(transform)

    def get_image_size(self):
        return self.transform.image_size

    def get_x(self, i):
        return open_image(os.path.join(self.path, self.fnames[i]))

    def get_n(self):
        return len(self.fnames)

    def resize_imgs(self, targ, new_path):
        dest = resize_imgs(self.fnames, targ, self.path, new_path)
        return self.__class__(self.fnames, self.y, self.transform, dest)

    def denorm(self, arr):
        """Reverse the normalization done to a batch of images.

        Arguments:
            arr: of shape/size (N,3,get_image_size,get_image_size)
        """
        if type(arr) is not np.ndarray:
            arr = to_np(arr)
        if len(arr.shape) == 3:
            arr = arr[None]
        return self.transform.denorm(np.rollaxis(arr, 1, 4))


class FilesArrayDataset(FilesDataset):

    def __init__(self, fnames, y, transform, path):
        self.y = y
        assert len(fnames) == len(y)
        super().__init__(fnames, transform, path)

    def get_y(self, i):
        return self.y[i]

    def get_c(self):
        return self.y.shape[1] if len(self.y.shape) > 1 else 0


class FilesIndexArrayDataset(FilesArrayDataset):

    def get_c(self):
        return int(self.y.max()) + 1


class FilesNhotArrayDataset(FilesArrayDataset):

    @property
    def is_multi(self):
        return True


class FilesIndexArrayRegressionDataset(FilesArrayDataset):

    def is_reg(self):
        return True


class ArraysDataset(BaseDataset):

    def __init__(self, x, y, transform):
        self.x, self.y = x, y
        assert len(x) == len(y)
        super().__init__(transform)

    def get_x(self, i):
        return self.x[i]

    def get_y(self, i):
        return self.y[i]

    def get_n(self):
        return len(self.y)

    def get_image_size(self):
        return self.x.shape[1]


class ArraysIndexDataset(ArraysDataset):

    def get_c(self):
        return int(self.y.max()) + 1

    def get_y(self, i):
        return self.y[i]


class ArraysNhotDataset(ArraysDataset):

    def get_c(self):
        return self.y.shape[1]

    @property
    def is_multi(self):
        return True


class ModelData():

    def __init__(self, path, training_downloader, validation_downloader, test_downloader=None):
        self.path, self.training_downloader, self.validation_downloader, self.test_downloader = path, training_downloader, validation_downloader, test_downloader

    @classmethod
    def from_dls(cls, path, training_downloader, validation_downloader, test_downloader=None):
        # training_downloader,validation_downloader = DataLoader(training_downloader),DataLoader(validation_downloader)
        # if test_downloader: test_downloader = DataLoader(test_downloader)
        return cls(path, training_downloader, validation_downloader, test_downloader)

    @property
    def is_reg(self):
        return self.training_dataset.is_reg

    @property
    def is_multi(self):
        return self.training_dataset.is_multi

    @property
    def training_dataset(self):
        return self.training_downloader.dataset

    @property
    def validation_dataset(self):
        return self.validation_downloader.dataset

    @property
    def test_dataset(self):
        return self.test_downloader.dataset

    @property
    def trn_y(self):
        return self.training_dataset.y

    @property
    def val_y(self):
        return self.validation_dataset.y


class ImageData(ModelData):

    def __init__(self, path, datasets, batch_size, num_workers, classes):
        training_dataset, validation_dataset, fix_ds, aug_ds, test_dataset, test_aug_ds = datasets
        self.path, self.batch_size, self.num_workers, self.classes = path, batch_size, num_workers, classes
        self.training_downloader, self.validation_downloader, self.fix_dl, self.aug_dl, self.test_downloader, self.test_aug_dl = [
            self.get_dl(ds, shuf)
            for ds, shuf in [
                (training_dataset, True),
                (validation_dataset, False),
                (fix_ds, False),
                (aug_ds, False),
                (test_dataset, False),
                (test_aug_ds, False),
            ]
        ]

    def get_dl(self, ds, shuffle):
        if ds is None:
            return None
        return DataLoader(
            ds,
            batch_size=self.batch_size,
            shuffle=shuffle,
            num_workers=self.num_workers,
            pin_memory=False,
        )

    @property
    def image_size(self):
        return self.training_dataset.image_size

    @property
    def c(self):
        return self.training_dataset.c

    def resized(self, dl, targ, new_path):
        return dl.dataset.resize_imgs(targ, new_path) if dl else None

    def resize(self, targ_image_size, new_path="tmp"):
        new_ds = []
        dls = [self.training_downloader, self.validation_downloader, self.fix_dl, self.aug_dl]
        if self.test_downloader:
            dls += [self.test_downloader, self.test_aug_dl]
        else:
            dls += [None, None]
        t = tqdm_notebook(dls)
        for dl in t:
            new_ds.append(self.resized(dl, targ_image_size, new_path))
        t.close()
        return self.__class__(
            new_ds[0].path, new_ds, self.batch_size, self.num_workers, self.classes
        )

    @staticmethod
    def get_ds(fn, trn, val, tfms, test=None, **kwargs):
        res = [
            fn(trn[0], trn[1], tfms[0], **kwargs),  # train
            fn(val[0], val[1], tfms[1], **kwargs),  # val
            fn(trn[0], trn[1], tfms[1], **kwargs),  # fix
            fn(val[0], val[1], tfms[0], **kwargs),  # aug
        ]
        if test is not None:
            if isinstance(test, tuple):
                test_lbls = test[1]
                test = test[0]
            else:
                test_lbls = np.zeros((len(test), 1))
            res += [
                fn(test, test_lbls, tfms[1], **kwargs),  # test
                fn(test, test_lbls, tfms[0], **kwargs),  # test_aug
            ]
        else:
            res += [None, None]
        return res


class ImageClassifierData(ImageData):

    @classmethod
    def from_arrays(
        cls,
        path,
        trn,
        val,
        batch_size=64,
        tfms=(None, None),
        classes=None,
        num_workers=4,
        test=None,
    ):
        """ Read in images and their labels given as numpy arrays

        Arguments:
            path: a root path of the data (used for storing trained models, precomputed values, etc)
            trn: a tuple of training data matrix and target label/classification array (e.g. `trn=(x,y)` where `x` has the
                shape of `(5000, 784)` and `y` has the shape of `(5000,)`)
            val: a tuple of validation data matrix and target label/classification array.
            batch_size: batch size
            tfms: transformations (for data augmentations). e.g. output of `tfms_from_model`
            classes: a list of all labels/classifications
            num_workers: a number of workers
            test: a matrix of test data (the shape should match `trn[0]`)

        Returns:
            ImageClassifierData
        """
        datasets = cls.get_ds(ArraysIndexDataset, trn, val, tfms, test=test)
        return cls(path, datasets, batch_size, num_workers, classes=classes)

    @classmethod
    def from_paths(
        cls,
        path,
        batch_size=64,
        tfms=(None, None),
        trn_name="train",
        val_name="valid",
        test_name=None,
        test_with_labels=False,
        num_workers=8,
    ):
        """ Read in images and their labels given as sub-folder names

        Arguments:
            path: a root path of the data (used for storing trained models, precomputed values, etc)
            batch_size: batch size
            tfms: transformations (for data augmentations). e.g. output of `tfms_from_model`
            trn_name: a name of the folder that contains training images.
            val_name:  a name of the folder that contains validation images.
            test_name:  a name of the folder that contains test images.
            num_workers: number of workers

        Returns:
            ImageClassifierData
        """
        assert not (
            tfms[0] is None or tfms[1] is None
        ), "please provide transformations for your train and validation sets"
        trn, val = [folder_source(path, o) for o in (trn_name, val_name)]
        if test_name:
            test = folder_source(
                path, test_name
            ) if test_with_labels else read_dir(
                path, test_name
            )
        else:
            test = None
        datasets = cls.get_ds(
            FilesIndexArrayDataset, trn, val, tfms, path=path, test=test
        )
        return cls(path, datasets, batch_size, num_workers, classes=trn[2])

    @classmethod
    def from_csv(
        cls,
        path,
        folder,
        csv_fname,
        batch_size=64,
        tfms=(None, None),
        val_idxs=None,
        suffix="",
        test_name=None,
        continuous=False,
        skip_header=True,
        num_workers=8,
    ):
        """ Read in images and their labels given as a CSV file.

        This method should be used when training image labels are given in an CSV file as opposed to
        sub-directories with label names.

        Arguments:
            path: a root path of the data (used for storing trained models, precomputed values, etc)
            folder: a name of the folder in which training images are contained.
            csv_fname: a name of the CSV file which contains target labels.
            batch_size: batch size
            tfms: transformations (for data augmentations). e.g. output of `tfms_from_model`
            val_idxs: index of images to be used for validation. e.g. output of `get_cv_idxs`.
                If None, default arguments to get_cv_idxs are used.
            suffix: suffix to add to image names in CSV file (sometimes CSV only contains the file name without file
                    extension e.g. '.jpg' - in which case, you can set suffix as '.jpg')
            test_name: a name of the folder which contains test images.
            continuous: TODO
            skip_header: skip the first row of the CSV file.
            num_workers: number of workers

        Returns:
            ImageClassifierData
        """
        fnames, y, classes = csv_source(
            folder, csv_fname, skip_header, suffix, continuous=continuous
        )
        return cls.from_names_and_array(
            path,
            fnames,
            y,
            classes,
            val_idxs,
            test_name,
            num_workers=num_workers,
            suffix=suffix,
            tfms=tfms,
            batch_size=batch_size,
            continuous=continuous,
        )

    @classmethod
    def from_names_and_array(
        cls,
        path,
        fnames,
        y,
        classes,
        val_idxs=None,
        test_name=None,
        num_workers=8,
        suffix="",
        tfms=(None, None),
        batch_size=64,
        continuous=False,
    ):
        val_idxs = get_cv_idxs(len(fnames)) if val_idxs is None else val_idxs
        ((val_fnames, trn_fnames), (val_y, trn_y)) = split_by_idx(
            val_idxs, np.array(fnames), y
        )

        test_fnames = read_dir(path, test_name) if test_name else None
        if continuous:
            f = FilesIndexArrayRegressionDataset
        else:
            f = FilesIndexArrayDataset if len(
                trn_y.shape
            ) == 1 else FilesNhotArrayDataset
        datasets = cls.get_ds(
            f,
            (trn_fnames, trn_y),
            (val_fnames, val_y),
            tfms,
            path=path,
            test=test_fnames,
        )
        return cls(path, datasets, batch_size, num_workers, classes=classes)


def split_by_idx(idxs, *a):
    """
    Split each array passed as *a, to a pair of arrays like this (elements selected by idxs,  the remaining elements)
    This can be used to split multiple arrays containing training data to validation and training set.

    :param idxs [int]: list of indexes selected
    :param a list: list of np.array, each array should have same amount of elements in the first dimension
    :return: list of tuples, each containing a split of corresponding array from *a.
            First element of each tuple is an array composed from elements selected by idxs,
            second element is an array of remaining elements.
    """
    mask = np.zeros(len(a[0]), dtype=bool)
    mask[np.array(idxs)] = True
    return [(o[mask], o[~mask]) for o in a]
