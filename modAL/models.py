"""
Core models for active learning algorithms.
"""

import numpy as np
from sklearn.utils import check_array
from modAL.utils.validation import check_class_labels, check_class_proba
from modAL.uncertainty import uncertainty_sampling
from modAL.disagreement import vote_entropy_sampling


class ActiveLearner:
    """
    This class is an abstract model of a general active learning algorithm.

    Parameters
    ----------
    predictor: scikit-learn estimator
        The estimator to be used in the active learning loop.

    query_strategy: function
        Function providing the query strategy for the active learning
        loop, for instance modAL.uncertainty.uncertainty_sampling.

    training_samples: None or numpy.ndarray of shape (n_samples, n_features)
        Initial training samples, if available.

    training_labels: None or numpy.ndarray of shape (n_samples, )
        Initial training labels corresponding to initial training samples

    fit_kwargs: keyword arguments for the fit method

    Attributes
    ----------
    predictor: scikit-learn estimator
        The estimator to be used in the active learning loop.

    uncertainty_measure: function
        Function providing the uncertainty measure, for instance
        modAL.uncertainty.classifier_uncertainty.

    query_strategy: function
        Function providing the query strategy for the active learning
        loop, for instance modAL.query.max_uncertainty.

    _training_samples: None numpy.ndarray of shape (n_samples, n_features)
        If the model hasn't been fitted yet: None
        If the model has been fitted already: numpy.ndarray containing the
        samples which the model has been trained on

    _training_labels: None or numpy.ndarray of shape (n_samples, )
        If the model hasn't been fitted yet: None
        If the model has been fitted already: numpy.ndarray containing the
        labels corresponding to _training_samples

    Examples
    --------
    >>> import numpy as np
    >>> from sklearn.datasets import load_iris
    >>> from sklearn.ensemble import RandomForestClassifier
    >>> from modAL.models import ActiveLearner
    >>>
    >>> iris = load_iris()
    >>> # give initial training examples
    >>> X_training = iris['data'][[0, 50, 100]]
    >>> y_training = iris['target'][[0, 50, 100]]
    >>>
    >>> # initialize active learner
    >>> learner = ActiveLearner(
    ...     predictor=RandomForestClassifier(),
    ...     X_initial=X_training, y_initial=y_training
    ... )
    >>>
    >>> # querying for labels
    >>> query_idx, query_sample = learner.query(iris['data'])
    >>>
    >>> # ...obtaining new labels from the Oracle...
    >>>
    >>> # teaching newly labelled examples
    >>> learner.teach(
    ...     X=iris['data'][query_idx].reshape(1, -1),
    ...     y=iris['target'][query_idx].reshape(1, )
    ... )

    """
    def __init__(
            self,
            predictor,                                           # scikit-learner estimator object
            query_strategy=uncertainty_sampling,	             # callable to query labels
            X_initial=None, y_initial=None,	                     # initial data if available
            **fit_kwargs                                         # keyword arguments for fitting the initial data
    ):
        assert callable(query_strategy), 'query_function must be callable'

        self._predictor = predictor
        self.query_strategy = query_strategy

        if type(X_initial) == type(None) and type(y_initial) == type(None):
            self._X_training = None
            self._y_training = None
        elif type(X_initial) != type(None) and type(y_initial) != type(None):
            self._X_training = check_array(X_initial)
            self._y_training = check_array(y_initial, ensure_2d=False)
            self._fit_to_known(**fit_kwargs)

    def _add_training_data(self, X, y):
        """
        Adds the new data and label to the known data, but does
        not retrain the model.

        Parameters
        ----------
        X: numpy.ndarray of shape (n_samples, n_features)
            The new samples for which the labels are supplied
            by the expert.

        y: numpy.ndarray of shape (n_samples, )
            Labels corresponding to the new instances in X.

        Note
        ----
        If the classifier has been fitted, the features in X
        have to agree with the training samples which the
        classifier has seen.
        """
        X, y = check_array(X), check_array(y, ensure_2d=False)
        assert len(X) == len(y), 'the number of new data points and number of labels must match'

        if type(self._X_training) != type(None):
            try:
                self._X_training = np.vstack((self._X_training, X))
                self._y_training = np.concatenate((self._y_training, y))
            except ValueError:
                raise ValueError('the dimensions of the new training data and label must'
                                 'agree with the training data and labels provided so far')

        else:
            self._X_training = X
            self._y_training = y

    def _fit_to_known(self, **fit_kwargs):
        """
        Fits self._predictor to the training data and labels provided to it so far.

        Parameters
        ----------
        fit_kwargs: keyword arguments
            Keyword arguments to be passed to the fit method of the predictor.
        """
        self._predictor.fit(self._X_training, self._y_training, **fit_kwargs)

    def fit(self, X, y, **fit_kwargs):
        """
        Interface for the fit method of the predictor. Fits the predictor
        to the supplied data, then stores it internally for the active
        learning loop.

        Parameters
        ----------
        X: numpy.ndarray of shape (n_samples, n_features)
            The samples to be fitted.

        y: numpy.ndarray of shape (n_samples, )
            The corresponding labels.

        fit_kwargs: keyword arguments
            Keyword arguments to be passed to the fit method of the predictor.

        DANGER ZONE
        -----------
        When using scikit-learn estimators, calling this method will make the
        ActiveLearner forget all training data it has seen!
        """
        self._predictor.fit(X, y, **fit_kwargs)
        self._X_training = X
        self._y_training = y

    def predict(self, X, **predict_kwargs):
        """
        Estimator predictions for X. Interface with the predict
        method of the estimator.

        Parameters
        ----------
        X: numpy.ndarray of shape (n_samples, n_features)
            The samples to be predicted.

        predict_kwargs: keyword arguments
            Keyword arguments to be passed to the predict method of the classifier.

        Returns
        -------
        pred: numpy.ndarray of shape (n_samples, )
            Estimator predictions for X.
        """
        return self._predictor.predict(X, **predict_kwargs)

    def predict_proba(self, X, **predict_proba_kwargs):
        """
        Class probabilities if the predictor is a classifier.
        Interface with the predict_proba method of the classifier.

        Parameters
        ----------
        X: numpy.ndarray of shape (n_samples, n_features)
            The samples for which the class probabilities are
            to be predicted.

        predict_proba_kwargs: keyword arguments
            Keyword arguments to be passed to the predict_proba method of the
            classifier.

        Returns
        -------
        proba: numpy.ndarray of shape (n_samples, n_classes)
            Class probabilities for X.
        """
        return self._predictor.predict_proba(X, **predict_proba_kwargs)

    def query(self, X, **query_kwargs):
        """
        Finds the n_instances most informative point in the data provided by calling
        the query_strategy function. Returns the queried instances and its indices.

        Parameters
        ----------
        X: numpy.ndarray of shape (n_samples, n_features)
            The pool of samples from which the query strategy should choose
            instances to request labels.

        query_kwargs: keyword arguments
            Keyword arguments for the uncertainty measure function

        Returns
        -------
        query_idx: numpy.ndarray of shape (n_instances, )
            The indices of the instances from X_pool chosen to be labelled.

        X[query_idx]: numpy.ndarray of shape (n_instances, n_features)
            The instances from X_pool chosen to be labelled.
        """
        check_array(X, ensure_2d=True)

        query_idx, query_instances = self.query_strategy(self._predictor, X, **query_kwargs)
        return query_idx, query_instances

    def score(self, X, y, **score_kwargs):
        """
        Interface for the score method of the predictor.

        Parameters
        ----------
        X: numpy.ndarray of shape (n_samples, n_features)
            The samples for which prediction accuracy is to be calculated

        y: numpy.ndarray of shape (n_samples, )
            Ground truth labels for X

        score_kwargs: keyword arguments
            Keyword arguments to be passed to the .score() method of the
            classifier

        Returns
        -------
        mean_accuracy: numpy.float containing the mean accuracy of the predictor
        """
        return self._predictor.score(X, y, **score_kwargs)

    def teach(self, X, y, **fit_kwargs):
        """
        Adds X and y to the known training data and retrains the predictor
        with the augmented dataset.

        Parameters
        ----------
        X: numpy.ndarray of shape (n_samples, n_features)
            The new samples for which the labels are supplied
            by the expert.

        y: numpy.ndarray of shape (n_samples, )
            Labels corresponding to the new instances in X.

        fit_kwargs: keyword arguments
            Keyword arguments to be passed to the fit method
            of the predictor.
        """
        self._add_training_data(X, y)
        self._fit_to_known(**fit_kwargs)


class Committee:
    """
    This class is an abstract model of a committee-based active learning algorithm.

    Parameters
    ----------
    learner_list: list
        A list of ActiveLearners forming the Committee.

    query_strategy: function
        Query strategy function. Committee supports disagreement-based query strategies
        from modAL.disagreement, but uncertainty-based strategies from modAL.uncertainty
        are also supported.

    Attributes
    ----------
    classes_: numpy.ndarray of shape (n_classes, )
        Class labels known by the Committee.

    n_classes_: int
        Number of classes known by the Committee

    Examples
    --------
    >>> import numpy as np
    >>> from sklearn.datasets import load_iris
    >>> from sklearn.neighbors import KNeighborsClassifier
    >>> from sklearn.ensemble import RandomForestClassifier
    >>> from modAL.models import ActiveLearner, Committee
    >>>
    >>> iris = load_iris()
    >>>
    >>> # initialize ActiveLearners
    >>> learner_1 = ActiveLearner(
    ...     predictor=RandomForestClassifier(),
    ...     X_initial=iris['data'][[0, 50, 100]], y_initial=iris['target'][[0, 50, 100]]
    ... )
    >>> learner_2 = ActiveLearner(
    ...     predictor=KNeighborsClassifier(n_neighbors=3),
    ...     X_initial=iris['data'][[1, 51, 101]], y_initial=iris['target'][[1, 51, 101]]
    ... )
    >>>
    >>> # initialize the Committee
    >>> committee = Committee(
    ...     learner_list=[learner_1, learner_2]
    ... )
    >>>
    >>> # querying for labels
    >>> query_idx, query_sample = committee.query(iris['data'])
    >>>
    >>> # ...obtaining new labels from the Oracle...
    >>>
    >>> # teaching newly labelled examples
    >>> committee.teach(
    ...     X=iris['data'][query_idx].reshape(1, -1),
    ...     y=iris['target'][query_idx].reshape(1, )
    ... )

    """
    def __init__(
            self,
            learner_list,                                        # list of ActiveLearner objects
            query_strategy=vote_entropy_sampling                 # callable to query labels

    ):
        assert type(learner_list) == list, 'learners must be supplied in a list'

        self._learner_list = learner_list
        self.query_strategy = query_strategy

        self._set_classes()

    def __iter__(self):
        for learner in self._learner_list:
            yield learner

    def __len__(self):
        return len(self._learner_list)

    def _add_training_data(self, X, y):
        """
        Adds the new data and label to the known data for each learner,
        but does not retrain the model.

        Parameters
        ----------
        X: numpy.ndarray of shape (n_samples, n_features)
            The new samples for which the labels are supplied
            by the expert.

        y: numpy.ndarray of shape (n_samples, )
            Labels corresponding to the new instances in X.

        Note
        ----
        If the learners have been fitted, the features in X
        have to agree with the training samples which the
        classifier has seen.
        """
        for learner in self._learner_list:
            learner._add_training_data(X, y)
        self._set_classes()

    def _fit_to_known(self, **fit_kwargs):
        """
        Fits all learners to the training data and labels provided to it so far.

        Parameters
        ----------
        fit_kwargs: keyword arguments
            Keyword arguments to be passed to the fit method of the predictor.
        """
        for learner in self._learner_list:
            learner._fit_to_known(**fit_kwargs)

    def _set_classes(self):
        """
        Checks the known class labels by each learner, merges the labels and
        returns a mapping which maps the learner's classes to the complete label
        list.
        """

        # assemble the list of known classes from each learner
        self.classes_ = np.unique(
            np.concatenate(tuple(learner._predictor.classes_ for learner in self._learner_list), axis=0),
            axis=0
        )
        self.n_classes_ = len(self.classes_)

    def predict(self, X, **predict_proba_kwargs):
        """
        Predicts the class of the samples by picking the consensus prediction.

        Parameters
        ----------
        X: numpy.ndarray of shape (n_samples, n_features)
            The samples to be predicted.

        predict_proba_kwargs: keyword arguments
            Keyword arguments to be passed to the predict_proba method of the
            Committee.

        Returns
        -------
        prediction: numpy.ndarray of shape (n_samples, )
            The predicted class labels for X.

        """
        # getting average certainties
        proba = self.predict_proba(X, **predict_proba_kwargs)
        # finding the sample-wise max probability
        max_proba_idx = np.argmax(proba, axis=1)
        # translating label indices to labels
        return self.classes_[max_proba_idx]

    def predict_proba(self, X, **predict_proba_kwargs):
        """
        Consensus probabilities of the Committee.

        Parameters
        ----------
        X: numpy.ndarray of shape (n_samples, n_features)
            The samples for which the class probabilities are
            to be predicted.

        predict_proba_kwargs: keyword arguments
            Keyword arguments to be passed to the predict_proba method of the
            Committee.

        Returns
        -------
        proba: numpy.ndarray of shape (n_samples, n_classes)
            Class probabilities for X.
        """
        return np.mean(self.vote_proba(X, **predict_proba_kwargs), axis=1)

    def query(self, X, **query_kwargs):
        """
        Finds the n_instances most informative point in the data provided by calling
        the query_strategy function. Returns the queried instances and its indices.

        Parameters
        ----------
        X: numpy.ndarray of shape (n_samples, n_features)
            The pool of samples from which the query strategy should choose
            instances to request labels.

        query_kwargs: keyword arguments
            Keyword arguments for the uncertainty measure function

        Returns
        -------
        query_idx: numpy.ndarray of shape (n_instances, )
            The indices of the instances from X_pool chosen to be labelled.

        X[query_idx]: numpy.ndarray of shape (n_instances, n_features)
            The instances from X_pool chosen to be labelled.
        """
        check_array(X, ensure_2d=True)

        query_idx, query_instances = self.query_strategy(self, X, **query_kwargs)
        return query_idx, X[query_idx]

    def teach(self, X, y, **fit_kwargs):
        """
        Adds X and y to the known training data for each learner
        and retrains the Committee with the augmented dataset.

        Parameters
        ----------
        X: numpy.ndarray of shape (n_samples, n_features)
            The new samples for which the labels are supplied
            by the expert.

        y: numpy.ndarray of shape (n_samples, )
            Labels corresponding to the new instances in X.

        fit_kwargs: keyword arguments
            Keyword arguments to be passed to the fit method
            of the predictor.
        """
        self._add_training_data(X, y)
        self._fit_to_known(**fit_kwargs)

    def vote(self, X, **predict_kwargs):
        """
        Predicts the labels for the supplied data for each learner in
        the Committee.

        Parameters
        ----------
        X: numpy.ndarray of shape (n_samples, n_features)
            The samples to cast votes.

        predict_kwargs: keyword arguments
            Keyword arguments to be passed for the learners .predict() method.

        Returns
        -------
        vote: numpy.ndarray of shape (n_samples, n_learners)
            The predicted class probability for each learner in the Committee
            and each sample in X.
        """
        check_array(X, ensure_2d=True)
        prediction = np.zeros(shape=(X.shape[0], len(self._learner_list)))

        for learner_idx, learner in enumerate(self._learner_list):
            prediction[:, learner_idx] = learner.predict(X, **predict_kwargs)

        return prediction

    def vote_proba(self, X, **predict_proba_kwargs):
        """
        Predicts the probabilities of the classes for each sample and each learner.

        Parameters
        ----------
        X: numpy.ndarray of shape (n_samples, n_features)
            The samples for which class probabilities are to be calculated.

        predict_proba_kwargs: keyword arguments
            Keyword arguments for the .predict_proba() method of the learners.

        Returns
        -------
        vote_proba: numpy.ndarray of shape (n_samples, n_learners, n_classes)
            Probabilities of each class for each learner and each instance.

        """

        check_array(X, ensure_2d=True)

        # get dimensions
        n_samples = X.shape[0]
        n_learners = len(self._learner_list)
        proba = np.zeros(shape=(n_samples, n_learners, self.n_classes_))

        # checking if the learners in the Committee know the same set of class labels
        if check_class_labels(*[learner._predictor for learner in self._learner_list]):
            # known class labels are the same for each learner
            # probability prediction is straightforward

            for learner_idx, learner in enumerate(self._learner_list):
                proba[:, learner_idx, :] = learner.predict_proba(X, **predict_proba_kwargs)

        else:
            for learner_idx, learner in enumerate(self._learner_list):
                proba[:, learner_idx, :] = check_class_proba(
                    proba=learner.predict_proba(X, **predict_proba_kwargs),
                    known_labels=learner._predictor.classes_,
                    all_labels=self.classes_
                )

        return proba


if __name__ == '__main__':
    import doctest
    doctest.testmod()