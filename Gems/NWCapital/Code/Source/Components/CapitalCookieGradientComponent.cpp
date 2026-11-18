/*
 * Copyright (c) Contributors to the Open 3D Engine Project.
 * For complete copyright and license terms please see the LICENSE at the root of this distribution.
 *
 * SPDX-License-Identifier: Apache-2.0 OR MIT
 *
 */

#include <NWCapital/Components/CapitalCookieGradientComponent.h>
#include <AzCore/Math/MathUtils.h>
#include <AzCore/RTTI/BehaviorContext.h>
#include <AzCore/Serialization/EditContext.h>
#include <AzCore/Serialization/SerializeContext.h>

namespace NWCapital
{
    void CapitalCookie::Reflect(AZ::ReflectContext* context)
    {
        AZ::SerializeContext* serialize = azrtti_cast<AZ::SerializeContext*>(context);
        if (serialize)
        {
            serialize->Class<CapitalCookie>()
                ->Version(0)
                ->Field("Position", &CapitalCookie::m_position)
                ->Field("InnerRadius", &CapitalCookie::m_innerRadius)
                ->Field("OuterRadius", &CapitalCookie::m_outerRadius)
                ->Field("MaxHeightBlend", &CapitalCookie::m_maxHeightBlend)
                ->Field("EdgeNoise", &CapitalCookie::m_edgeNoise)
                ->Field("EdgeNoiseFeatureSize", &CapitalCookie::m_edgeNoiseFeatureSize)
                ->Field("GroundNoiseScale", &CapitalCookie::m_groundNoiseScale)
                ;

            AZ::EditContext* edit = serialize->GetEditContext();
            if (edit)
            {
                edit->Class<CapitalCookie>("Capital Cookie", "New World capital terrain stamp")
                    ->DataElement(nullptr, &CapitalCookie::m_position, "Position", "Capital world position; Z is the flattened height.")
                    ->DataElement(nullptr, &CapitalCookie::m_innerRadius, "Inner Radius", "Fully flattened radius in metres.")
                    ->DataElement(nullptr, &CapitalCookie::m_outerRadius, "Outer Radius", "Outer edge of the blend ring in metres.")
                    ->DataElement(nullptr, &CapitalCookie::m_maxHeightBlend, "Max Height Blend", "Blend strength cap, 0..1.")
                    ->DataElement(nullptr, &CapitalCookie::m_edgeNoise, "Edge Noise", "Ring-edge noise amplitude factor.")
                    ->DataElement(nullptr, &CapitalCookie::m_edgeNoiseFeatureSize, "Edge Noise Feature Size", "Noise feature scale (reserved).")
                    ->DataElement(nullptr, &CapitalCookie::m_groundNoiseScale, "Ground Noise Scale", "Ground noise scale (reserved; client behaviour unverified).")
                    ;
            }
        }
    }

    void CapitalCookieGradientConfig::Reflect(AZ::ReflectContext* context)
    {
        CapitalCookie::Reflect(context);

        AZ::SerializeContext* serialize = azrtti_cast<AZ::SerializeContext*>(context);
        if (serialize)
        {
            serialize->Class<CapitalCookieGradientConfig, AZ::ComponentConfig>()
                ->Version(0)
                ->Field("Gradient", &CapitalCookieGradientConfig::m_gradientSampler)
                ->Field("Cookies", &CapitalCookieGradientConfig::m_cookies)
                ->Field("HeightMin", &CapitalCookieGradientConfig::m_heightMin)
                ->Field("HeightMax", &CapitalCookieGradientConfig::m_heightMax)
                ;

            AZ::EditContext* edit = serialize->GetEditContext();
            if (edit)
            {
                edit->Class<CapitalCookieGradientConfig>("NW Capital Cookie Gradient", "")
                    ->ClassElement(AZ::Edit::ClassElements::EditorData, "")
                    ->Attribute(AZ::Edit::Attributes::Visibility, AZ::Edit::PropertyVisibility::ShowChildrenOnly)
                    ->Attribute(AZ::Edit::Attributes::AutoExpand, true)
                    ->DataElement(nullptr, &CapitalCookieGradientConfig::m_gradientSampler, "Gradient", "Source heightmap gradient to stamp.")
                    ->DataElement(nullptr, &CapitalCookieGradientConfig::m_cookies, "Cookies", "Capital terrain stamps to apply.")
                    ->DataElement(nullptr, &CapitalCookieGradientConfig::m_heightMin, "Height Min", "World height at gradient value 0.")
                    ->DataElement(nullptr, &CapitalCookieGradientConfig::m_heightMax, "Height Max", "World height at gradient value 1.")
                    ;
            }
        }

        if (auto behaviorContext = azrtti_cast<AZ::BehaviorContext*>(context))
        {
            behaviorContext->Class<CapitalCookieGradientConfig>()
                ->Constructor()
                ->Property("gradientSampler", BehaviorValueProperty(&CapitalCookieGradientConfig::m_gradientSampler))
                ->Property("cookies", BehaviorValueProperty(&CapitalCookieGradientConfig::m_cookies))
                ;
        }
    }

    void CapitalCookieGradientComponent::GetProvidedServices(AZ::ComponentDescriptor::DependencyArrayType& services)
    {
        services.push_back(AZ_CRC_CE("GradientService"));
    }

    void CapitalCookieGradientComponent::GetIncompatibleServices(AZ::ComponentDescriptor::DependencyArrayType& services)
    {
        services.push_back(AZ_CRC_CE("GradientService"));
    }

    void CapitalCookieGradientComponent::GetRequiredServices([[maybe_unused]] AZ::ComponentDescriptor::DependencyArrayType& services)
    {
    }

    void CapitalCookieGradientComponent::Reflect(AZ::ReflectContext* context)
    {
        CapitalCookieGradientConfig::Reflect(context);

        AZ::SerializeContext* serialize = azrtti_cast<AZ::SerializeContext*>(context);
        if (serialize)
        {
            serialize->Class<CapitalCookieGradientComponent, AZ::Component>()
                ->Version(0)
                ->Field("Configuration", &CapitalCookieGradientComponent::m_configuration)
                ;
        }

        if (auto behaviorContext = azrtti_cast<AZ::BehaviorContext*>(context))
        {
            behaviorContext->Constant("CapitalCookieGradientComponentTypeId", BehaviorConstant(CapitalCookieGradientComponentTypeId));
        }
    }

    CapitalCookieGradientComponent::CapitalCookieGradientComponent(const CapitalCookieGradientConfig& configuration)
        : m_configuration(configuration)
    {
    }

    void CapitalCookieGradientComponent::Activate()
    {
        m_dependencyMonitor.Reset();
        m_dependencyMonitor.ConnectOwner(GetEntityId());
        m_dependencyMonitor.ConnectDependency(m_configuration.m_gradientSampler.m_gradientId);

        // Connect to GradientRequestBus last so that everything is initialized before listening for gradient queries.
        GradientSignal::GradientRequestBus::Handler::BusConnect(GetEntityId());
    }

    void CapitalCookieGradientComponent::Deactivate()
    {
        // Disconnect from GradientRequestBus first to ensure no queries are in process when deactivating.
        GradientSignal::GradientRequestBus::Handler::BusDisconnect();
        m_dependencyMonitor.Reset();
    }

    bool CapitalCookieGradientComponent::ReadInConfig(const AZ::ComponentConfig* baseConfig)
    {
        if (auto config = azrtti_cast<const CapitalCookieGradientConfig*>(baseConfig))
        {
            m_configuration = *config;
            return true;
        }
        return false;
    }

    bool CapitalCookieGradientComponent::WriteOutConfig(AZ::ComponentConfig* outBaseConfig) const
    {
        if (auto config = azrtti_cast<CapitalCookieGradientConfig*>(outBaseConfig))
        {
            *config = m_configuration;
            return true;
        }
        return false;
    }

    float CapitalCookieGradientComponent::StampHeight(float height, float x, float y) const
    {
        // Client formula (tools/physics/terrain_ground.py):
        //   width = max(outer - inner, 1e-4)
        //   amp   = width * edgeNoise * 0.5
        //   u     = 1 - clamp((dist - (inner + amp)) / width, 0, 1)
        //   w     = (3 - 2u) * u^2 * maxHeightBlend
        //   new   = old + (flat - old) * w
        for (const CapitalCookie& cookie : m_configuration.m_cookies)
        {
            const float dx = x - cookie.m_position.GetX();
            const float dy = y - cookie.m_position.GetY();
            const float dist = AZStd::sqrt(dx * dx + dy * dy);

            const float width = AZ::GetMax(cookie.m_outerRadius - cookie.m_innerRadius, 1e-4f);
            const float amp = width * cookie.m_edgeNoise * 0.5f;
            const float u = 1.0f - AZ::GetClamp((dist - (cookie.m_innerRadius + amp)) / width, 0.0f, 1.0f);
            if (u <= 0.0f)
            {
                continue;
            }
            const float w = (3.0f - 2.0f * u) * u * u * cookie.m_maxHeightBlend;
            height += (cookie.m_position.GetZ() - height) * w;
        }
        return height;
    }

    float CapitalCookieGradientComponent::GetValue(const GradientSignal::GradientSampleParams& sampleParams) const
    {
        const float v = AZ::GetClamp(m_configuration.m_gradientSampler.GetValue(sampleParams), 0.0f, 1.0f);
        const float range = m_configuration.m_heightMax - m_configuration.m_heightMin;
        float height = m_configuration.m_heightMin + v * range;
        height = StampHeight(height, sampleParams.m_position.GetX(), sampleParams.m_position.GetY());
        return AZ::GetClamp((height - m_configuration.m_heightMin) / range, 0.0f, 1.0f);
    }

    void CapitalCookieGradientComponent::GetValues(AZStd::span<const AZ::Vector3> positions, AZStd::span<float> outValues) const
    {
        if (positions.size() != outValues.size())
        {
            AZ_Assert(false, "input and output lists are different sizes (%zu vs %zu).", positions.size(), outValues.size());
            return;
        }

        const float range = m_configuration.m_heightMax - m_configuration.m_heightMin;
        m_configuration.m_gradientSampler.GetValues(positions, outValues);
        for (size_t i = 0; i < positions.size(); ++i)
        {
            const float v = AZ::GetClamp(outValues[i], 0.0f, 1.0f);
            float height = m_configuration.m_heightMin + v * range;
            height = StampHeight(height, positions[i].GetX(), positions[i].GetY());
            outValues[i] = AZ::GetClamp((height - m_configuration.m_heightMin) / range, 0.0f, 1.0f);
        }
    }

    bool CapitalCookieGradientComponent::IsEntityInHierarchy(const AZ::EntityId& entityId) const
    {
        return m_configuration.m_gradientSampler.IsEntityInHierarchy(entityId);
    }
}
