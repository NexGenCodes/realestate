import logging
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel
from django.db import models
from .models import Property

logger = logging.getLogger(__name__)


class PropertyRecommender:
    """
    Content-based recommendation engine for properties.
    Uses TF-IDF on property descriptions and features to find similarities.
    """

    def __init__(self):
        self._vectorizer = TfidfVectorizer(stop_words="english")
        self._matrix = None
        self._indices = None
        self._df = None

    def _prepare_data(self):
        """
        Loads active properties and fits the TF-IDF vectorizer.
        In a production env, this should be cached or computed periodically via Celery.
        For now, we compute on demand (or simple in-memory caching if instance persists).
        """
        # 1. Fetch Data
        properties = Property.objects.filter(
            status=Property.Status.AVAILABLE, is_banned=False
        ).values("id", "title", "description", "property_type", "category", "city")

        if not properties:
            return

        self._df = pd.DataFrame(properties)

        # 2. Feature Engineering
        # Combine relevant text fields into a single 'soup'
        self._df["soup"] = (
            self._df["title"]
            + " "
            + self._df["description"]
            + " "
            + self._df["property_type"]
            + " "
            + self._df["category"]
            + " "
            + self._df["city"]
        )

        # 3. Compute TF-IDF Matrix
        # Replace NaN with empty string just in case
        self._df["soup"] = self._df["soup"].fillna("")
        self._matrix = self._vectorizer.fit_transform(self._df["soup"])

        # 4. Map IDs to indices
        self._indices = pd.Series(
            self._df.index, index=self._df["id"]
        ).drop_duplicates()

    def get_recommendations(self, property_id, limit=5):
        """
        Return a QuerySet of similar properties.
        """
        try:
            # Lazy load data
            if self._matrix is None:
                self._prepare_data()

            if self._df is None or self._matrix is None:
                return Property.objects.none()

            # Check if property exists in our current dataframe
            if property_id not in self._indices:
                # If it's a new property not yet in the 'cache', we might need to reload
                # or just return generic similar based on category (fallback).
                # Reloading for now for correctness (but expensive).
                self._prepare_data()
                if property_id not in self._indices:
                    return Property.objects.none()

            # Get index of the property
            idx = self._indices[property_id]

            # Compute similarity for this specific property against all others
            # linear_kernel is equivalent to cosine_similarity for normalized vectors (TF-IDF is normalized)
            cosine_sim = linear_kernel(self._matrix[idx], self._matrix).flatten()

            # Get pairwise similarity scores
            sim_scores = list(enumerate(cosine_sim))

            # Sort by similarity
            sim_scores = sorted(sim_scores, key=lambda x: x[1], reverse=True)

            # Get scores of the 'limit' most similar properties
            # Skip the first one (itself)
            sim_scores = sim_scores[1 : limit + 1]

            # Get the property indices
            property_indices = [i[0] for i in sim_scores]

            # Return ID list
            target_ids = self._df.iloc[property_indices]["id"].tolist()

            # Preserve order is tricky with SQL 'IN', use Case/When if strict order needed
            # For this feature, just returning the set is often "good enough" visually,
            # but let's try to preserve order.
            preserved = models.Case(
                *[models.When(pk=pk, then=pos) for pos, pk in enumerate(target_ids)]
            )
            return Property.objects.filter(pk__in=target_ids).order_by(preserved)

        except Exception as e:
            logger.error(f"Recommendation engine error: {e}")
            # Fallback to empty
            return Property.objects.none()
